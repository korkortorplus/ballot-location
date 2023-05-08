set dotenv-load

# dvc
set_dvc:
    dvc remote modify --local bucket access_key_id $AWS_ACCESS_KEY_ID
    dvc remote modify --local bucket secret_access_key $AWS_SECRET_ACCESS_KEY

    dvc remote modify --local gdrive gdrive_client_id $GDRIVE_CLIENT_ID
    dvc remote modify --local gdrive gdrive_client_secret $GDRIVE_CLIENT_SECRET

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

download_poom_ballot:
    wget https://raw.githubusercontent.com/heypoom/voting-station-locations/main/locations.csv -O data/poom_ballot_location.csv

