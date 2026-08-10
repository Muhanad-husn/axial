"""The local operator console (issue #689): a Streamlit app that puts a face
on capability the `axial` CLI already has.

There is exactly one user, on one machine, and the CLI already does every one
of these jobs correctly, so the console does none of them itself: it shells
out to `axial` (`cli_bridge`) and reads what the pipeline already persists
under `data/` (`monitor`, over `axial.runlog`'s reader API). A console that
only calls the CLI cannot break the pipeline -- that is the whole design
rationale, and it is why nothing in this package imports a pass module.

`app` is the Streamlit script itself, launched by `axial console`. Streamlit
lives in its own `[dependency-groups]` entry (`operator`), so importing this
package is not free for anything that does not want it; nothing under
`src/axial` outside this package imports it.
"""
