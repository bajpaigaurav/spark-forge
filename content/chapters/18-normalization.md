## 18. Keeping the residual stream in range

A transformer block has two sublayers. The first is attention, the second is a feed-forward MLP. Each sublayer reads the residual stream, computes a function, and adds its output back onto the stream. For block l with input x_l, the pre-norm form is

a_l = x_l + Attn(LN(x_l))

x_{l+1} = a_l + MLP(LN(a_l))

The post-norm form is

a_l = LN(x_l + Attn(x_l))

x_{l+1} = LN(a_l + MLP(a_l))

The residual stream is the shared vector that every block reads and writes. Anthropic's 2021 "A Mathematical Framework for Transformer Circuits" gave it that name. Nothing overwrites the stream; each block adds to it. The stream is the only path connecting the first layer to the last.

The residual addition gives backpropagation an identity path. For a vector function f, write J_f for its Jacobian, the matrix of partial derivatives. A pre-norm block has output y = x + f(LN(x)), so

∂y/∂x = I + J_f(LN(x)) J_LN(x).

The identity matrix I is the direct path. Through N blocks, the chain rule multiplies these Jacobians. Expanding the product gives the identity term plus terms with one or more J_f factors. The identity term carries a gradient component through every addition without multiplying it by a sublayer Jacobian. That identity path gives gradient a route through every block that does not multiply by a sublayer Jacobian. It is one reason deep stacks can train, though it does not guarantee that the gradient at the first block is at least as large as the gradient at the last. The total Jacobian is a sum, and the other terms can cancel the identity term.

Take a scalar simplification. Let LN have derivative s and the sublayer function have derivative a. For one pre-norm block, ∂y/∂x = 1 + a s. For two blocks with derivatives a and b, the gradient at the input is (1 + b s)(1 + a s) times the upstream gradient. Set s = 1, a = -1, b = 0. The product is zero. The identity term in the first block is present, but the sublayer derivative cancels it. A depth comparison therefore has to look at the whole product, not just at the presence of I.

The stream's norm also needs a recurrence, not an assumption. With x_{l+1} = x_l + f_l(x_l),

||x_{l+1}||^2 = ||x_l||^2 + 2 x_l·f_l(x_l) + ||f_l(x_l)||^2.

The cross term decides the direction. If f_l points along x_l, the norm grows. If it points against x_l, the norm can shrink. If it is orthogonal, the squared norm grows by ||f_l||^2: ||x_{l+1}||^2 = ||x_l||^2 + ||f_l||^2. Over N blocks with a constant additive f_l = a, x_N = x_0 + N a, so the vector grows linearly; its norm is ||x_0 + Na|| = sqrt(||x_0||^2 + 2N⟨x_0,a⟩ + N^2||a||^2), which grows asymptotically linearly in N (exactly linear only in special cases such as x_0 parallel to a). With f_l = -x_l/2, x_{l+1} = x_l/2, so the norm halves each block. A model can have either behavior; the initialization and the learned functions decide which.

LayerNorm arrived in July 2016 from Jimmy Lei Ba, Jamie Ryan Kiros and Geoffrey Hinton. Their problem was recurrent networks. Batch normalization computes statistics across the batch for each feature separately, which is awkward when every timestep has a different effective batch and sequences have different lengths. Ba and colleagues normalized per token and across the feature dimension. For a vector x with d components,

μ = (1/d) Σ x_i

σ = sqrt((1/d) Σ (x_i - μ)^2 + ε)

y_i = γ_i (x_i - μ)/σ + β_i.

The mean and variance come from one token's own vector, so the result does not depend on what else is in the batch. That is a batch-invariance property. It does not make the KV cache safe. The KV cache stores, for each layer and each past token, the key and value vectors produced by that layer. Future tokens attend to those stored vectors under a causal mask. Cache safety comes from causal masking and from treating past entries as read-only, not from the normalization's per-token statistics.

The gamma and beta matter. Without them the layer would emit zero-mean, unit-variance output and throw away a deliberate offset that a later layer might detect. With them, normalization becomes a reparameterization. Take x = [2, 4, 6, 8]. The mean is 5, so the centered vector is [-3, -1, 1, 3]. The variance is (9 + 1 + 1 + 9)/4 = 5, the standard deviation is about 2.236, and the normalized vector is [-1.342, -0.447, 0.447, 1.342]. Set gamma to all ones and beta to all zeros and that is the output. Ignoring ε (or in the limit ε→0), multiplying the input by 10 leaves the output unchanged; with ε>0, scale invariance is only approximate. Adding 100 to every component still leaves the output unchanged exactly. LayerNorm makes a layer's input invariant to scale and to shift.

Zhang and Sennrich asked in 2019 which half of that invariance was doing the work. Their paper, "Root Mean Square Layer Normalization", dropped the mean subtraction and kept the scaling. RMSNorm divides x by the root mean square of its components,

r = sqrt((1/d) Σ x_i^2 + ε)

y_i = γ_i x_i / r.

On the same vector, the mean of squares is (4 + 16 + 36 + 64)/4 = 30, the root mean square is about 5.477, and the output is [0.365, 0.730, 1.095, 1.461]. That output has mean 0.913, so RMSNorm does not center anything. It is invariant to scaling and not to shifting. Zhang and Sennrich argued from their experiments that re-centering contributed little and re-scaling did the work. Dropping the mean removes one reduction, one elementwise subtraction and the beta parameters at every normalization site. LLaMA used RMSNorm in 2023. The operation count falls; whether that shows up as wall-clock time depends on the kernel and the model.

Placement changes which Jacobian multiplies the residual path. Pre-norm puts normalization inside the sublayer input, so the residual addition is outside the norm. Post-norm puts normalization after the addition, so the residual path passes through the norm. In post-norm, a block has output y = LN(x + f(x)), so

∂y/∂x = J_LN(x + f(x)) (I + J_f(x)).

The identity path is still there, but it is multiplied by the LayerNorm Jacobian. For a vector x with d components, the exact LayerNorm Jacobian is

∂y_i/∂x_j = (γ_i/σ)[δ_ij - 1/d - z_i z_j/d],

where z_i = (x_i - μ)/σ. This is not a single scalar inverse standard deviation. It has a centering term, a per-coordinate term, and a cross term z_i z_j. Take x = [2, 4, 6], γ = 1, β = 0. Then μ = 4, σ = sqrt(8/3) ≈ 1.633, and z = [-1.225, 0, 1.225]. The Jacobian is approximately

[[0.102, -0.204, 0.102],

 [-0.204, 0.408, -0.204],

 [0.102, -0.204, 0.102]].

The diagonal entries differ by a factor of four, and the matrix maps a constant vector to zero. The gradient through the residual path therefore depends on the activation pattern, not only on the standard deviation.

Xiong and colleagues at Microsoft Research Asia and Peking University analyzed post-norm gradients in February 2020. They showed that post-norm transformers need learning-rate warmup because gradient norms at initialization can be large and unstable, and that pre-norm transformers avoid that particular instability. The mechanism is the one above. In post-norm, the residual path is multiplied by J_LN, and at initialization the activation scale can make that factor large. Warmup keeps the early updates small enough to survive it. Pre-norm bypasses that multiplication on the identity path. GPT-3 used pre-norm in 2020. Pre-norm trades stream-scale control for gradient-path control.

Because the stream is never normalized inside a pre-norm block, its norm can drift. The recurrence above shows the drift can go up or down, but nothing in the block pulls the stream back to a fixed scale. A final normalization after the last block and before the unembedding gives the unembedding a controlled input scale. The final norm computes h = LN(x_L) and the unembedding computes logits = W_U h. It does not bound the stream inside the blocks. The last block's output and the first block's output can have different norms, and the final norm handles that difference at the model's exit.

Attention has its own magnitude problem. For a query q and a key k, the logit is q·k, which equals ||q|| ||k|| cos θ. If training pushes the norms upward, the logits grow. Softmax over large logits saturates. Take two logits, 0 and 12. The softmax probabilities are about 6.14 × 10^-6 and 0.99999386. The softmax Jacobian has entries p_i(δ_ij - p_j). Its largest entry is about 6.14 × 10^-6. With logits 0 and 1, the probabilities are 0.269 and 0.731, and the Jacobian entries are about 0.197. The saturated case passes almost no gradient back to the logits. That is the collapse.

A concrete QK example shows the same thing. Let d_head = 2, q = [10, 0], k1 = [10, 0], k2 = [0, 10]. The scaled logits are 100/√2 ≈ 70.7 and 0. Softmax gives a weight of nearly 1 to k1 and nearly 0 to k2. With q = [1, 0], k1 = [1, 0], k2 = [0, 1], the scaled logits are 0.707 and 0, and the softmax weights are 0.669 and 0.331. The first case has a collapsed gradient; the second does not.

Alex Henry and colleagues proposed normalizing queries and keys in October 2020. Mostafa Dehghani and colleagues applied LayerNorm to q and k in ViT-22B in 2023. QK-norm normalizes q and k after the linear projection and before the dot product; with a learned gamma it controls the pre-gamma normalized scale, but gamma can rescale q and k, so it does not impose a hard bound on q/k or logits. It can use LayerNorm or RMSNorm. The choice changes whether mean subtraction happens. Apply it after W_Q and W_K and after reshaping into heads, and normalize over the head dimension d_head. Use a learned gamma vector of length d_head, initialized to ones. Gamma can be shared across heads or separate per head. The logits become

logits_{h,i,j} = (q̃_{h,i} · k̃_{h,j}) / sqrt(d_head),

with q̃_h = Norm(W_Q^h x; γ_Q^h) and k̃_h = Norm(W_K^h x; γ_K^h). QK-norm does not bound the residual stream. It targets a different site where magnitude can grow. Each normalization site has its own failure mode, and a norm at one site does not fix another.

The range question connects to the compute format. bf16 has eight exponent bits and seven fraction bits. It has a wide exponent range, similar to fp32, but only about three decimal digits of precision. fp16 has five exponent bits and ten fraction bits. It has more precision but a much smaller range; its largest finite value is 65504. A dot product of two vectors with components near 100 over 64 dimensions can reach 640,000, which overflows fp16. Normalizing q and k before the dot product keeps the product inside the representable range. Softmax saturation is a separate loss. Even when the logits are representable, a probability near 1 gives a Jacobian near zero. Mixed precision keeps master weights in fp32 and runs matrix multiplies in bf16 or fp16; fp16 training also uses loss scaling to keep small gradients representable. A model that keeps its residual stream and attention logits inside the exponent range of its compute format can use the narrower format without overflow. A model that fails to do so will lose gradients at the softmax or produce infinities at the dot product. The next chapter follows that arithmetic into bf16 and fp16, where exponent range and mantissa width set the limits.