FROM python:3.12.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 ARROW_NUM_THREADS=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY pilot ./pilot
COPY configs ./configs
COPY tests ./tests
COPY scripts ./scripts
COPY .env.vm.example ./
ENTRYPOINT ["python", "-m", "pilot"]
CMD ["--help"]
