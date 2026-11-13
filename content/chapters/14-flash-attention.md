## Attention That Never Builds the Matrix

A GPU is a stack of memories, and the distances between the layers explain most of what modern attention kernels do. Start with the execution model, since everything later leans on it. A kernel launches a grid of thread blocks. Each block runs on one streaming multiprocessor and contains some number of warps, each warp 32 threads that execute in lockstep. Registers belong to individual threads. Shared memory belongs to the block, is sized at launch, and is the only scratchpad a block has for sharing data between warps without going back out to global memory.

Registers hold a few hundred bytes per thread and are effectively free to read. Shared memory runs to tens or a couple hundred kilobytes per SM, addressed in tens of cycles. Then L2, shared across the chip. Then the unified LPDDR5X pool, the large address space where tensors actually live.

### The bandwidth gap and latency

The bandwidth gap is the number that matters. HBM3 on an H100 delivers 3,350 GB/s across the whole part. Shared memory on a single SM moves 128 bytes per clock, and a Hopper SM runs at roughly 1.8 GHz, so one SM's scratchpad sustains about 128 bytes per clock times that rate. Hopper packs 132 SMs into one package, so the aggregate scratchpad bandwidth outruns the memory system by more than an order of magnitude. That is the ratio in its bluntest form.

Latency tells the same story from the other side. A shared-memory load retires in tens of cycles. A miss to HBM costs several hundred. A kernel that touches HBM pays per byte and pays again per round trip.

### Why naive attention cannot materialize the score matrix

Standard attention, as Vaswani and colleagues specified it in 2017, does exactly that. Take one head with queries Q, keys K, values V, each of shape L × d. The first step forms S = QKᵀ, an L × L matrix. Take a long-document prompt of 100,000 tokens, so L = 100,000, and a typical head width of d = 128. Then L² is 10¹⁰ entries, and at two bytes each, S occupies 20 GB for a single head in a single layer.

Run the roofline on that. Forming S costs 2L²d = 2.56 × 10¹² FLOPs. Materializing it is the problem. Stored in fp16 at L = 100,000 and d = 128, the score matrix for a single head occupies L × L × 2 bytes, 20 GB, so all d heads of one layer occupy L × L × d × 2 bytes, which is 2.56 TB. No accelerator holds that, which is why naive attention is not merely slow but impossible at this length; the matrix must be produced tile by tile and consumed as it is produced. Softmax needs the row maximum before any element can be finalized, so a kernel that writes S out and reads it back four times moves five times the matrix through memory. At 3,350 GB/s of HBM3, moving 2.56 TB once takes 2.56 TB ÷ 3,350 GB/s = 0.76 seconds. Doing it five times costs 3.8 seconds for one layer, which is more than an H100 spends on a whole model pass at this length.

The arithmetic intensity of that kernel comes to 8.74 × 10¹² FLOPs divided by 2.19 × 10¹³ bytes, or about 0.4 FLOPs per byte. To be compute-bound at that intensity the machine would have to sustain 0.4 × 3,350 = 1.3 TFLOP/s from memory alone. It does not, because the kernel stalls on the four round trips. The matmuls are cheap by comparison. The materialization dominates.

### FlashAttention's tiling fix

That diagnosis is what Tri Dao, Daniel Fu, Stefano Ermon, Atri Rudra and Christopher Ré published in 2022 as "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness." The title states the method. Count the bytes, not the FLOPs.

Their fix is tiling, borrowed from cache-aware numerical linear algebra. Split Q into row blocks of size Br and K, V into column blocks of size Bc. Load one Q block and one K block into shared memory, compute the Br × Bc score tile, apply the softmax pieces to it, multiply by the matching V block, and accumulate into a Br × d output block that also stays on chip. Advance to the next K block. The L × L matrix never exists anywhere.

Tile sizes follow from the shared-memory budget rather than from taste. With d = 128 and fp16 operands, a Br = 128 Q tile takes 128 × 128 × 2 = 32 KB. A Bc = 64 K tile takes 64 × 128 × 2 = 16 KB, the matching V tile another 16 KB, and the Br × Bc score tile 128 × 64 × 2 = 16 KB. That totals 80 KB. NVIDIA's Hopper tuning guide lists a maximum of 228 KB of shared memory per SM, so one block fits comfortably and leaves room for double buffering, which is what lets the next K tile load while the current one is being multiplied. The Ampere tuning guide lists 164 KB per SM, which fits the same configuration with room for double-buffered K and V, and even double-buffered Q, though not comfortably for all four buffers. That shared-memory budget—together with register/accumulator pressure and occupancy—is what sets the tile shape, not the arithmetic alone; a 16×128 fp32 accumulator slice already costs 64 registers per thread per warp

The block runs 8 warps. Each warp owns a 16-row strip of the Q tile and the corresponding 16 × d accumulator slice for those rows, held in registers The QKᵀ product issues as warp-level matrix multiply-accumulate instructions, and the score tile stays in registers, where row-wise softmax is computed with warp-level reductions/shuffles. One detail bites here. Shared memory is banked in 32 banks of 4 bytes, a 128-byte period. A row of the score tile at Bc = 64 fp16 is 128 bytes, exactly one period,, so every row starts on the same bank and a column-wise read serializes into 32-way conflicts. Padding the row stride to 136 elements moves each row's start by 16 bytes and spreads the accesses across banks.

### Online softmax and the rescaling identity

One obstruction stands in the way, and it is why this is an algorithm rather than a loop reorganization. Softmax needs two quantities per row, the maximum score and the sum of exponentials, and neither is known until every key has been seen. Process keys in tiles and the maximum arrives late.

Online softmax, published by Maxim Milakov and Natalia Gimelshein in 2018 and adopted by Dao's group, resolves it. Keep a running maximum m and a running sum l. When a tile arrives carrying a larger maximum, rescale the accumulated state by α = exp(m_old − m_new). The validity of that rescaling is a one-line derivation. The accumulator after the old tiles is O_old = Σ_j exp(s_j − m_old) v_j. Rewriting each term in the new scale gives exp(s_j − m_new) = exp(s_j − m_old) · exp(m_old − m_new), and since the factor is constant across the row it factors straight out of the sum, so O_new = α · O_old + Σ_{j∈tile} exp(s_j − m_new) v_j. The same factor applies to l, because l is a sum of the same exponentials.

Here is the loop.

```
for each K/V tile j:
    s = Q_tile @ K_j^T            # Br x Bc
    m_tile = rowmax(s)
    m_new  = max(m, m_tile)
    alpha  = exp(m - m_new)       # Br x 1
    l      = l * alpha + rowsum(exp(s - m_new))
    O      = O * alpha + exp(s - m_new) @ V_j
    m      = m_new
O = O / l
```

A numeric pass makes the rescaling concrete. Suppose the first tile yields scores 1.0 and 2.0 for one row, and the second tile yields 3.0 and 0.5. After tile one, m = 2.0, the exponentials are exp(−1) = 0.3679 and exp(0) = 1.0, and l = 1.3679, with O holding 0.3679·v₁ + 1.0·v₂. Tile two brings a larger maximum, so α = exp(2.0 − 3.0) = 0.3679. The running sum becomes 1.3679 × 0.3679 = 0.5033 and O is scaled by the same 0.3679. Adding tile two's contributions, exp(0) = 1.0 and exp(−2.5) = 0.0821, gives l = 1.5854. The full-matrix softmax with the global maximum of 3.0 gives 0.1353 + 0.3679 + 1.0 + 0.0821 = 1.5853. The two agree once intermediate values are not rounded; using unrounded intermediates gives l = 1.5853

On the question of exactness, the running maximum is a max over values that are already exactly representable, so it is exact. Every exponent argument is therefore ≤ 0, so no exponential overflows. Underflow happens only for scores more than about 103 below the maximum in fp32 (with subnormals beginning around 87 below). and those terms contribute nothing to the sum in any case. What remains is rounding. Each rescale multiplies the accumulator by a factor and rounds, so relative error grows with the number of tiles, on the order of one unit in the last place per tile in fp32. The naive kernel accumulates the same class of error over its single pass. Flash Attention adds a small multiple of it and nothing else.

### Backward pass recomputation and linear footprint

The backward pass is where the memory savings turn dramatic. Ordinary attention stores the L × L matrix from the forward pass so the gradient can reuse it. Flash Attention stores none of it and recomputes the score tiles from Q, K and V during the backward pass, then applies the chain rule through softmax using the recomputed scores and the stored row normalization. The cost is one extra QKᵀ per head-layer, 2.56 × 10¹² FLOPs, against 20 GB of storage saved. That trade is not close on any single GPU. An H100 holds 192 GB of HBM in total, and dividing 192 by 20 gives 9.6, so the full score matrices for nine head-layers would consume the entire card. A 100,000-token prefill touches thousands of head-layers.

The footprint drops from quadratic to linear in sequence length. Per head, the quadratic term is 2L² bytes and the linear term is the K and V themselves, 4Ld bytes. The ratio is L/2d, which at L = 100,000 and d = 128 comes to 390×. Concretely, the score matrix for one head of one layer is 20 GB in fp16, while the keys and values it summarizes are 100,000 × 128 = 12,800,000 values per tensor, so keys and values together at two bytes each are 2 × 12,800,000 × 2 = 51,200,000 bytes. That is what made long-context models practical. A KV pool holding 262,144 positions would need a stored score matrix larger again by the square of the ratio between the two lengths.

### Scheduling rewrites and the decode wall

Flash Attention 2, published by Dao in 2023, is a scheduling rewrite. The first version rescaled the Br × d accumulator on every tile iteration and divided by l inside the loop. Both operations are elementwise work on 128 × 128 = 16,384 values, against 2·128·64·128 = 2.1 × 10⁶ FLOPs in the matmul for the same tile, so by count they look negligible. They are not, because exp and the elementwise multiply issue on units that run at a small fraction of the matrix-multiply rate, and they serialize behind the matmul. The second version keeps O unnormalized and defers the division to the end, and it rescales only when the running maximum actually changes, which after the first few tiles is rare. It also reverses the loop so the K and V tile stays resident in shared memory while Q blocks stream past, cutting shared-memory traffic on K and V. and it partitions causal attention so that blocks working on early rows, which have few keys to visit, are paired with blocks working on late rows.

Flash Attention 3, from Jay Shah and colleagues in 2024, targets Hopper. Three mechanisms carry it. The Tensor Memory Accelerator is a copy engine that takes a descriptor giving a tile's shape and strides and moves it from global to shared memory in one instruction, asynchronously, without occupying registers or the load-store units. Warp specialization splits the block into producer warps that issue those copies and consumer warps that run the matrix multiplies, synchronized through mbarriers that track TMA copy completion, so copy and compute overlap without a software pipeline inside a single warp. And the matmuls run in fp8, e4m3, with a per-tile scale factor applied before the multiply and undone after, which doubles throughput against fp16 at a precision cost the scaling keeps bounded.

What Flash Attention does not fix is decode. During decode the model emits one token at a time and attention is a single query against a long row of cached keys and values. There is no L × L matrix to avoid, and the kernel is bandwidth-bound on the cache instead. Layout matters here. Keys and values are stored per layer, per KV head, per position, contiguous along the head dimension, so a decode step reads one long run rather than chasing a stride. At d = 128 in fp16, one KV head at one layer over the full 262,144-position pool occupies 262,144 × 128 × 2 = 67.1 MB for keys and the same for values, and 67.1 MB × 2 = 134.2 MB together, so every decode token reads that slab once per layer and per KV head — layers × KV heads × 134.2 MB in total, which is why the kernel is bandwidth-bound. Prefix sharing sits on top of that layout. Requests that begin with the same tokens map onto the same physical blocks through a radix tree over token blocks, so a shared system prompt is stored once and read by every request that uses it. When a workload shares a long system prompt, most prompt tokens hit the prefix cache and the prefill work they would otherwise cost is skipped. Flash-Decoding, also from Dao's group in 2023, splits the key sequence across blocks and merges the partial results with the same online rescaling, which helps long-context decode, though the dominant cost stays the bytes moved over the cache.

The same reasoning sets the shape of decode. A single stream reads the weights once per token and is bound by bandwidth, not arithmetic. Adding streams shares that read across the batch, so throughput rises sublinearly with concurrency. Prefill is the opposite: one pass over the weights serves every prompt token, so the arithmetic per byte stays high and the pass is compute-bound. The next chapter picks up at the cache, where the question becomes how many of those bytes a decode step actually has to touch.
