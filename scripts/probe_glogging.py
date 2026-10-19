import inspect
import gunicorn
import gunicorn.glogging as g

print(gunicorn.__version__)
print([n for n in dir(g) if "ormat" in n or "ogger" in n])
src = inspect.getsource(g)
i = src.find("def set_logger")
print(src[i:i + 1100])
j = src.find("access_log_format")
print("---- access_log_format use ----")
print(src[j - 400:j + 500])
