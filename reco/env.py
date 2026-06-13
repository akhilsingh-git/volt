import os
import json

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
LOG_FILE_PATH = os.environ.get("LOG_FILE_PATH", "app.log")


def get_model_metadata(model_name):
    file_path = "./models_meta/{}.json".format(model_name)

    with open(file_path, "r") as f:
        parsed_data = json.load(f)
        result = {
            "name": model_name,
            "data_date": parsed_data["Metadata"]["model_data_date"],
            "type": parsed_data["Metadata"]["model_type"],
            "arch": parsed_data["Metadata"]["model_arch"],
            "archive_name": parsed_data["Metadata"]["model_archive_name"],
            "content": parsed_data["Metadata"]["model_content"],
        }

    return result
