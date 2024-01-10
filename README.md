# VU Server

Full documentation including installing information can be found on the [VU1 portal](https://vudials.com/) and the [official VU Dials documentation.](https://docs.vudials.com/).

## Running from Source

For users running on windows, a native installer can be found on the [VU1 portal](https://vudials.com/). For users looking to install from the source code, the following will help you get started.

### Requirements

These instructions assume a basic proficiency with utilizing the command line. You'll also need to have installed [git](https://github.com/git-guides/install-git), [pyenv](https://github.com/pyenv/pyenv), have an [installed version of python 3.9](https://github.com/pyenv/pyenv), and [pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv).

### Installation

```bash
git clone https://github.com/SasaKaranovic/VU-Server.git #Clone this repo.
cd VU-Server #Navigate into our folder.
pyenv virtualenv-init 3.9 VU-Server #Create a virtualENV for this project
pyenv local VU-Server #Activate the virtualENV whenever you are in this folder.
pip install -r requirements.txt #Install dependencies.
python server.py #Run the server.
```
