# this script will clean the cache files before any necessary build
# clean __pycache__ folder from NextSSL folder and its subfolders
import os
import shutil

def clean_pycache():
    for root, dirs, _ in os.walk('.', topdown=False):
        if '__pycache__' in dirs:
            pycache_dir = os.path.join(root, '__pycache__')
            shutil.rmtree(pycache_dir)
            print(f"Removed: {pycache_dir}")
        if '.pytest_cache' in dirs:
            pytest_cache_dir = os.path.join(root, '.pytest_cache')
            shutil.rmtree(pytest_cache_dir)
            print(f"Removed: {pytest_cache_dir}")
        if '.mypy_cache' in dirs:
            mypy_cache_dir = os.path.join(root, '.mypy_cache')
            shutil.rmtree(mypy_cache_dir)
            print(f"Removed: {mypy_cache_dir}")

if __name__ == "__main__":
    clean_pycache()