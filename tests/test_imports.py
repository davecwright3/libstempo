def test_imports():
    import libstempo  # noqa: F401
    import libstempo.like  # noqa: F401
    import libstempo.emcee  # noqa: F401
    import libstempo.plot  # noqa: F401
    import libstempo.toasim  # noqa:F401
    import libstempo.eccUtils  # noqa: F401
    import libstempo.spharmORFbasis  # noqa: F401
    import libstempo.sandbox  # noqa: F401
    import libstempo.tim_file_analyzer  # noqa: F401


def test_tempo2_version_matches_install_script():
    """libstempo is compiled against the tempo2 tag pinned in install_tempo2.sh."""
    import re
    from pathlib import Path

    from packaging import version

    import libstempo

    script = (Path(__file__).parents[1] / "install_tempo2.sh").read_text()
    tag = re.search(r"^TEMPO2_TAG=(\S+)$", script, re.MULTILINE).group(1)
    assert libstempo.tempo2version() == version.parse(tag)
