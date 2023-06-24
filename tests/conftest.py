from click.testing import CliRunner
from git import Repo
from pathlib import Path
import pytest, tempfile


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def temp_git_repo():
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = Repo.init(temp_dir)
        with Path.open(Path(temp_dir, "test.txt"), "w") as f:
            f.write("This is a test file.")
        repo.index.add(["test.txt"])
        repo.index.commit("Initial commit")
        yield repo