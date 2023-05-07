set dotenv-load

# dvc
set_dvc:
    dvc remote modify --local bucket access_key_id $AWS_ACCESS_KEY_ID
    dvc remote modify --local bucket secret_access_key $AWS_SECRET_ACCESS_KEY

dvc-push:
    just run "dvc push"

hydrate_dotenv:
    #!/bin/bash
    cd {{invocation_directory()}}
    APP_ENV=OPENSOURCE
    eval $(op signin)
    op inject -i .env.tpl -o .env

run exec:
    #!/bin/bash
    cd {{invocation_directory()}}
    APP_ENV=OPENSOURCE
    eval $(op signin)
    op run --env-file .env.tpl -- {{ exec }}

# setup env
setup:
    #!/bin/bash
    
    # install kepler ref https://docs.kepler.gl/docs/keplergl-jupyter#install
    pip install keplergl

    jupyter labextension install @jupyter-widgets/jupyterlab-manager keplergl-jupyter