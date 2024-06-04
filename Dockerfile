FROM python:3.10
WORKDIR /code
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
# RUN pip install dask[dataframe]
# Add code for confidence metrics library
COPY ./src /code/src
EXPOSE 8080
CMD ["uvicorn","src.main:app", "--host", "0.0.0.0", "--port","8080"]