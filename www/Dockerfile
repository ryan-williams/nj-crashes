FROM python:3.12-slim AS dvc
RUN apt update -y \
 && apt-get install -y git wget \
 && pip install -U pip \
 && pip install dvc-s3 \
 && git clone --depth 1 -b server https://github.com/hudcostreets/nj-crashes src
WORKDIR src/www/public/njdot
RUN --mount=type=secret,id=aws,target=/root/.aws/credentials \
    dvc pull cmymc.db crashes.db drivers.db occupants.db pedestrians.db vehicles.db
WORKDIR ..
RUN wget -O njsp/crashes.db https://nj-crashes.s3.amazonaws.com/njsp/data/crashes.db

FROM node:22-slim
RUN npm i -g pnpm
COPY --from=dvc /src/www /src/www
WORKDIR /src/www
RUN pnpm i
RUN npm run build
ENTRYPOINT [ "npm", "run", "start", "--", "--port", "8080" ]
