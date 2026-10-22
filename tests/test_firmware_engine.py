import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_actual_cpp_firmware_engine(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Install a C++ compiler to run the shared firmware engine on the PC")
    output = tmp_path / "wake_engine_test.exe"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-pedantic",
        str(ROOT / "tests" / "wake_engine_test.cpp"),
        "-I", str(ROOT / "firmware" / "include"), "-o", str(output),
    ], check=True, capture_output=True, text=True)
    result = subprocess.run([str(output)], check=True, capture_output=True, text=True)
    assert result.stdout.startswith("PASS:")

