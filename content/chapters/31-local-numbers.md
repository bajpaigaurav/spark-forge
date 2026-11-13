## Chapter 31: Two small machines, by arithmetic

This chapter is a case study, not a benchmark. Two GB10 boxes sit on a desk with a cable between them, and nothing below was measured on that pair. Every number comes from a published specification or from arithmetic printed in the sentence that uses it. The question is how far the previous thirty chapters carry you before you plug anything in.

### Why a pair of small machines is interesting

NVIDIA's DGX Spark hardware guide describes one memory system for the GB10: LPDDR5X shared between the CPU and the GPU, moving at 273 GB/s, in a coherent pool of 128 GB per box. There is no separate VRAM on a faster path and no host memory to spill into. Weights, KV cache and live activations compete for the same bus.

That single number decides what the pair is good for. An H100 moves 3,350 GB/s, so one H100 sustains 3,350 ÷ 273 = 12.3 times the bandwidth of one GB10. A decode step is a bandwidth problem, so for single-stream work that ratio is close to the whole story. The pair's advantage is 256 GB of pool and a second memory bus at a price and power draw a single H100 does not reach.

Capacity is generous and bandwidth is the constraint. Keeping those two facts apart is most of what follows.

### The weight budget on one box

Start with what has to fit. A 70B model at four bits is 35 GB of weights. One box holds that inside its 128 GB pool with room left for cache and activations. The same model at FP16 is 140 GB, which does not fit in one box, so a single box cannot serve it at full precision no matter how the kernel is written.

Two boxes change the arithmetic twice. The pool doubles to 256 GB, so 140 GB fits. The model then has to be split, and the split is what costs you: every layer boundary that crosses the cable becomes a collective. Capacity is solved by adding a box, and the bill for adding it arrives in the next section.

The 4-bit case is the one worth carrying forward, because it is the configuration the rest of the book has been computing with. At 35 GB the weights fit on one box, so the pair is needed for context rather than for parameters.

### Splitting the model across the pair

Tensor parallelism splits each weight matrix by row or by column, so each rank holds half of every matrix rather than half of the layers. For a 70B model at four bits the shard is 35 GB ÷ 2 = 17.5 GB per rank. Each rank reads its own 17.5 GB per decode step and neither reads the other's half.

The split needs agreement at two points per transformer layer, after the attention output projection and after the MLP down-projection. A model with 32 layers therefore runs 2 × 32 = 64 all-reduces per forward pass. Each one moves the activation matrix in bf16 across the cable and blocks both ranks until it lands. At decode the batch is small, so the payload is small and the cost is latency rather than bandwidth. At prefill the matrix has one row per prompt token, so the payload grows with the prompt and the collective becomes a bandwidth problem of its own.

This is the structural difference between one box and two. On one box the decode step is one read of the weights and nothing else. On two boxes the same step is one read of half the weights plus 64 waits, and no roofline contains those waits.

### What the pair's roof looks like

The roofline for one rank follows from the two numbers already printed. One rank reads 17.5 GB per step and can read it at 273 GB/s, so its ceiling is 273 ÷ 17.5 = 15.6 tokens per second. Two ranks each produce tokens, so the aggregate ceiling is 2 × 15.6 = 31.2 tokens per second, provided the collectives are free. They are not free, so 31.2 is an upper bound the pair cannot reach.

Set the single card beside it. An H100 reads the whole 35 GB at 3,350 GB/s, so its batch-one ceiling is 3,350 ÷ 35 = 95.7 tokens per second. The ratio is 95.7 ÷ 31.2 = 3.07. One H100 is about three times the aggregate ceiling of the pair at batch one, and that comparison is generous to the pair because it ignores the collectives, which push the real figure lower.

The ratio does not make the pair useless. At batch one the pair is a bandwidth-limited box with a cable attached; at larger batches the shared weight read is amortised across rows and the picture changes. What the ratio does say is that the pair is not a substitute for a single fast card on latency-sensitive single-stream work.

### Where the arithmetic stops being enough

Three things the arithmetic leaves out, and each matters more than the last digit of 31.2.

The collectives come first. Every all-reduce has a fixed latency plus a transfer term, and 64 of them per forward pass serialise with the matmuls unless the implementation overlaps them with the next layer's compute. A pair on a fast link hides most of that. A pair on a slower link does not, and the published bandwidth says nothing about which link you have.

The KV cache comes second. The roofline above assumes the step reads only weights. At long context the cache is re-read for every active stream, so the bytes per step become the weights plus the cache, and the ceiling falls. The chapter on the step budget ran that arithmetic for a single card; the same arithmetic applies here with 17.5 GB in place of 35 GB, which makes the cache term relatively larger rather than smaller.

The third is the fraction of the roof a real kernel reaches. A published bandwidth is a peak. A decode kernel that reads 17.5 GB in small tiles reaches some fraction of 273 GB/s, and that fraction is the one number in this chapter that cannot be derived. It has to be measured on the pair, with the context length and the batch stated next to it. That is the job the methodology chapter describes.

### What this setup can and cannot answer

This chapter gives the shape of the answer. A 70B model at four bits fits on one box with room to spare. The pair doubles the pool and halves the per-rank weight read. The per-rank roof is 15.6 tokens per second and the aggregate roof is 31.2. A single H100's roof is 95.7, about three times higher. Every one of those figures follows from 273 GB/s, 35 GB and arithmetic printed beside it.

It cannot tell you what the pair will actually do. One configuration, one model size, one precision, and a roofline that is an upper bound rather than a result. The link between the boxes is unspecified. The achieved kernel bandwidth is unspecified. The context length is unspecified. Any of those can move the real number by a factor of two, and none can be filled in from a specification sheet.

What it can do is make a prediction checkable. Run the pair and see something far below 31.2 tokens per second at batch one, and the gap is collectives, kernel efficiency or cache traffic, in that order of likelihood. See something far above it, and one of the inputs is wrong, because a bandwidth roof is a roof. That is the use of a derived case study: it tells you which direction to be surprised in.
