import pathlib

path = pathlib.Path("tests/test_predictor.py")
s = path.read_text(encoding="utf-8")
s = s.replace("Json([0, 1, 2]), Json([])", "Json([0, 1, 2]), Json([])")  # no-op if already
s = s.replace("[0, 1, 2], []", "Json([0, 1, 2]), Json([])")
path.write_text(s, encoding="utf-8")
print("done")
