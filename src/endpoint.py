import flask
import os
from overall_points import scan_resume
import PyPDF2
import pdf2image
import db_connection as db
from resume_converter import resume_to_dict
import string
import random
import re
import sys
import traceback
import logging
import passwords
import airtable
from werkzeug.utils import secure_filename


logging.basicConfig(filename="out.log",filemode='a')

app = flask.Flask(__name__)
from flask_cors import CORS
CORS(app)

@app.route("/")
def healthcheck():
  return flask.jsonify({"status": 200, "message": "application is running"})

@app.route("/postResume", methods=['POST'])
def accept_resume():
  # save resume as file
  file = flask.request.files['file']
  glide_rename_index = 0

  new_filename = secure_filename(file.filename) # thank you andre

  if not is_valid_filetype(new_filename):
    return flask.jsonify({"success": False, "message": "File rejected - invalid filetype"})
  while os.path.exists("saved-resumes/"+new_filename):
    new_filename = new_filename.replace(".", "[GLIDE_"+str(glide_rename_index)+"].")
    glide_rename_index += 1
  file.save(os.path.join("saved-resumes/",new_filename))
  size = os.stat('saved-resumes/'+new_filename).st_size
  if (size > 2*1048576):
    os.remove("saved-resumes/"+new_filename)
    return flask.jsonify({"code": 400, "message": "File rejected - too big"})
  return flask.jsonify({"success": True, "filename": new_filename})

def is_valid_filetype(filename):
  return filename.endswith(".pdf") or filename.endswith(".doc") or filename.endswith(".docx")

@app.route("/getResumeDetails", methods=['POST'])
def parse_resume():
  json_body = flask.request.get_json()
  filename = json_body["filename"]
  did_user_opt_in = json_body["optIn"]
  is_development = json_body["isDev"]
  try:
    original_filename = remove_glide_index(filename)
    new_filename = generate_filename(filename)
    rename_file(filename, new_filename)
  except Exception as e:
    logging.exception(e)
    logging.error(msg="Unable to rename file: " + filename+"\n\n")
    return flask.jsonify({"success": False, "message": "There was an error in the request", "error": traceback.format_exc() })
  try:
    resume_as_dict = resume_to_dict(new_filename)
    scanned_data = scan_resume(original_filename, resume_as_dict, system_filename=new_filename)
    save_resume_to_db(
      original_filename,
      new_filename,
      did_user_opt_in,
      scanned_data,
      resume_as_dict,
      is_development
    )
  except Exception as e:
    logging.exception(e)
    logging.error(msg="Failed on file: " + new_filename+"\n\n")
    return flask.jsonify({"success": False, "message": "There was an error in the request", "error": traceback.format_exc() })
  img_filename = pdf_to_png(new_filename)
  host = ""
  if is_development:
    host = "http://localhost:5000"
  else:
    host = "https://glidecv.com/server"
  response = {
    "resumeJSON": resume_as_dict,
    "resumeImageSrc": host+"/getResumeImage?filename="+img_filename,
    "filename": original_filename,
    "success": True
  }
  response.update(scanned_data) # deconstruct scanned data and add to response
  return flask.jsonify(response)

@app.route("/getResumeImage")
def get_resume_jpg():
  return flask.send_from_directory("saved-images/", flask.request.args.get("filename"))

@app.route("/emailSignup")
def add_email():
  email = flask.request.args.get("email")
  try:
    success = airtable.add_email(email)
    return flask.jsonify({"success": success})
  except Exception as e:
    logging.exception(e)
    return flask.jsonify({"success": False})

@app.route("/countDocuments")
def count_documents():
  return flask.jsonify({"numDocuments": db.count_documents()})

@app.route("/access")
def access_file():
  if (authenticate(flask.request.args.get("api_key"))):
    return flask.send_from_directory("saved-resumes/", flask.request.args.get("filename"))
  return flask.jsonify({"message": "invalid credentials"})

def authenticate(key):
  return key == passwords.access_key()

def save_resume_to_db(filename, new_filename, did_user_opt_in, scanned_data, resume_as_json, is_development):
  entry = {
    "optIn": did_user_opt_in,
    "analysis": scanned_data,
    "resumeJSON": resume_as_json,
    "original_filename": filename,
    "saved_filename": new_filename,
    "isDev": is_development
  }
  db.add_entry(entry)

def pdf_to_png(filename):
  try:
    images = pdf2image.convert_from_path("saved-resumes/"+ filename, size = (300, None),first_page=1, last_page=1) 
    img_filename = os.path.splitext(filename)[0]+".jpg"
    for img in images: 
      img.save("saved-images/"+ img_filename, 'JPEG')
  except pdf2image.exceptions.PDFPageCountError:
    return "default.jpg"
  return img_filename

def remove_glide_index(filename):
  if re.search("\[GLIDE_[0-9]+\]", filename) != None:
    return re.sub("\[GLIDE_[0-9]+\]", "", filename)
  else:
    return filename

def generate_filename(filename):
  original_extension = filename[filename.rindex("."):]
  letters = string.ascii_uppercase
  nums = string.digits
  out = ""
  for i in range(10):
    if i % 2:
      out += random.choice(letters)
    else:
      out += random.choice(nums)
  out += original_extension
  if os.path.exists("saved-resumes/"+out):
    out = generate_filename(filename)
  return out

def rename_file(original_filename, new_filename):
  os.replace("saved-resumes/"+original_filename, "saved-resumes/"+new_filename)


if __name__ == "__main__":
  if len(sys.argv) < 2:
    if '/usr/bin' not in os.environ:
      os.environ['PATH'] = '/usr/bin'
  app.run(debug=True)

