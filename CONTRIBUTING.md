# Contributing

Thank you for your interest in AvangardeCam!

## How this repository works

AvangardeCam is developed by its author, following one vision of how a shop-floor CAM
should work. **Pull requests with code are not accepted** — every line that runs a machine
has to be one the author knows and trusts.

That does not close the door:

- **Bugs:** open an [issue](https://github.com/AvangardeCam/AvangardeCAM/issues/new/choose)
  with a small demo file. Never attach parts or drawings of your customers.
- **Ideas:** open an issue with the *Idea* form — what you need on the machine, not only
  which button.
- **Questions:** [Discussions](https://github.com/AvangardeCam/AvangardeCAM/discussions).

## Add your own functions: fork it

AvangardeCam is made to be extended with AI (see
[Extending with AI](README.md#extending-with-ai)). The licence (LGPL-2.1, postprocessors MIT)
lets you **fork** the repository and add whatever your shop needs:

1. Click *Fork* on GitHub, clone your fork into FreeCAD's `Mod` folder as `AvangardeCam`.
2. Give your AI assistant [ARCHITECTURE.md](ARCHITECTURE.md) and ask for the new function
   **in its own modules** (`model/`, `engine/`, `ui/`) with its own tests, without changing
   the code of other functions.
3. Run the tests (see [tests_gui/README.md](tests_gui/README.md)).
4. Check every new program in the simulation and on the machine (dry run, reduced feed)
   before cutting.

If you made something useful for others, tell about it in Discussions.
