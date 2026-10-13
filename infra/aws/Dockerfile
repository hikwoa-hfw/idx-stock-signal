# AWS Lambda Python 3.12 Container Image
FROM public.ecr.aws/lambda/python:3.12

# Install dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy application directories
COPY python/ ${LAMBDA_TASK_ROOT}/python/
COPY services/ ${LAMBDA_TASK_ROOT}/services/
COPY configs/ ${LAMBDA_TASK_ROOT}/configs/
COPY scripts/ ${LAMBDA_TASK_ROOT}/scripts/

# Set working directory & environment
ENV PYTHONPATH="${LAMBDA_TASK_ROOT}"
ENV APP_ENV="production"

# Default entry handler (can be overridden in template or invocation)
CMD ["python.cloud.handlers.lambda_daily_pipeline_handler"]
