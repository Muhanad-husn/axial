"""Stage-5 distillation eval (DEC-35, `plans/phase-a-completion/README.md`
stage 5): try to replace some per-chunk LLM tagging with cheap classifiers
trained on embeddings. Slice 5a (issue #296, this package's first module,
`axial.distill.embed`) embeds every prose chunk once and persists the
vectors in a LanceDB vector store. Later slices (5b clustering, 5c teacher
labels, 5d classifiers, 5e verdict) build on top of this package.
"""
