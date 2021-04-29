import os

def use_k8s_secret_envvars():
    for key, value in os.environ.items():
        if not key.startswith('K8S_SECRET_'):
            continue

        os.environ[key[11:]] = value
