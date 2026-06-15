# Anomaly Detection in ECG Signals of Heart Disease Prediction using Deep Learning Techniques

**A research-focused, industry-level deep learning project for ECG signal analysis, anomaly detection, and heart disease prediction support.**

---

## Project Lead

## Ashfakur Rahman

**Main Contributor and Project Lead**

---

## Team Members

* Md. Jahurul Islam Reday
* Md. Akash Hossain

---

## Supervisor

**Md. Solaiman Mia**
***Assistant Professor***
***Department of Computer Science and Engineering***
***Green University of Bangladesh***
Email: [solaiman@cse.green.edu.bd](mailto:solaiman@cse.green.edu.bd)

---

## Overview

**Anomaly Detection in ECG Signals of Heart Disease Prediction using Deep Learning Techniques** is a research-focused, industry-level deep learning project developed for ECG signal analysis, anomaly detection, and heart disease prediction support.

The system is designed as a modern healthcare AI web application that analyzes ECG data using a trained deep learning model. The application follows a deep learning first inference approach, where the exported `.keras` model is loaded locally, ECG signals are preprocessed, and prediction results are generated with confidence scores.

Along with ECG analysis, the platform includes a complete healthcare workflow with patient, doctor, and admin roles. It supports doctor approval, appointment handling, prescription management, prediction history, medical record access, and downloadable report generation.

This project was developed for research and educational purposes with a practical implementation approach inspired by real-world healthcare software architecture.

**Live Repository:** https://github.com/ashfak-g/ECG-Anomaly-Detection-Heart-Disease-Prediction

---

## Production Upgrade

The current version of **Anomaly Detection in ECG Signals of Heart Disease Prediction using Deep Learning Techniques** includes a working local model manager for the trained CNN + BiLSTM + Attention pipeline, direct ECG signal inference, model status reporting, secure upload handling, a JWT-secured REST API, optimized database performance, and a local PostgreSQL deployment path for development.

A Gemini fallback path is also available for image-based analysis when the local model path is not usable.

---

## Project Features

### Core AI and Medical Features

* Real deep learning inference pipeline using a trained CNN + BiLSTM + Multi-Head Self-Attention model.
* Local `.keras` model loading for ECG classification.
* Metadata-driven ECG signal preprocessing.
* Confidence score generation with prediction output.
* Optional Gemini-based image analysis fallback.
* ECG risk timeline with timestamp-based prediction history.
* Downloadable PDF report generation.
* AI chatbot endpoint for healthcare-related interaction.

### Security and Upload Handling

* Secure ECG upload validation.
* Magic byte checking instead of relying only on file extensions.
* Image integrity verification using `PIL`.
* Protection against corrupted or malicious files.
* Decompression bomb protection.
* EXIF metadata removal for patient privacy.
* UUID-based secure file renaming.
* Session hardening with secure cookie settings.
* Rate limiting for API abuse prevention.

### Clinical Workflow

* Role-based access control for patient, doctor, and admin users.
* Doctor registration and admin verification.
* Doctor availability slot management.
* Appointment request, cancellation, and rescheduling.
* Prescription writing and download support.
* Patient medical history access.
* Admin dashboard for doctor review, analytics, and audit logs.

### API and Performance

* JWT-secured REST API layer.
* PostgreSQL database integration.
* Optimized database queries using SQLAlchemy.
* Indexing for faster data retrieval.
* Redis-supported rate limiting.
* Gunicorn configuration for deployment readiness.

---

## Model Details

* **Model Type:** CNN + BiLSTM + Multi-Head Self-Attention
* **Input Format:** 187-length ECG signals
* **Classes:** `N`, `S`, `V`, `F`, `Q`
* **Model Artifacts:** Stored inside the `models/` directory
* **Tested Accuracy:** 97.44%
* **Tested AUC:** 0.998

---

## Installation and Local Run

### Prerequisites

* Python 3.11 or newer
* PostgreSQL
* TensorFlow/Keras
* Redis
* Git

### Clone the Repository

```bash
git clone https://github.com/ashfak-g/ECG-Anomaly-Detection-Heart-Disease-Prediction.git
cd ECG-Anomaly-Detection-Heart-Disease-Prediction
```

### Create and Activate a Virtual Environment

For Linux or macOS:

```bash
python3 -m venv venv
source venv/bin/activate
```

For Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Then update the `.env` file with your own configuration:

```env
SECRET_KEY=your_secret_key
DATABASE_URL=your_database_url
GEMINI_API_KEY=your_gemini_api_key
```

### Create Database Tables

Run the PostgreSQL schema file:

```bash
psql -U your_username -d your_database_name -f postgres_schema.sql
```

You can also create the required tables manually if your database is already configured.

### Run the Application

```bash
python3 run.py
```

The application will run locally at:

```bash
http://127.0.0.1:5000
```

---

## Quick Model Check

To verify that the trained model loads and inference works locally, run:

```bash
python test_ml_engine_direct.py
```

This script validates model loading, preprocessing, single-signal inference, and model metadata.

---

## Project Structure

```bash
├── app/
│   ├── __init__.py
│   ├── auth.py
│   ├── main.py
│   ├── models.py
│   ├── api/
│   ├── utils.py
│   ├── security.py
│   ├── ai.py
│   ├── ml_engine.py
│   ├── tasks.py
│   ├── static/
│   └── templates/
├── models/
├── config.py
├── gunicorn.conf.py
├── postgres_schema.sql
├── requirements.txt
└── run.py
```

---

## Technologies Used

### Backend

* Flask
* Gunicorn
* PostgreSQL
* SQLAlchemy

### Security

* Flask-Limiter
* Flask-JWT-Extended
* Flask-WTF
* PIL
* Secure session configuration

### Frontend

* Bootstrap 5
* JavaScript
* CSS3
* Leaflet Maps

### Artificial Intelligence and Machine Learning

* TensorFlow
* Keras
* CNN
* BiLSTM
* Multi-Head Self-Attention
* ECG signal classification
* Gemini API fallback

### Infrastructure

* PostgreSQL
* Redis
* Gunicorn

---

## Research Purpose

**Anomaly Detection in ECG Signals of Heart Disease Prediction using Deep Learning Techniques** was developed as a research-based implementation of deep learning techniques for ECG signal anomaly detection and heart disease prediction support.

The project demonstrates how a trained deep learning model can be integrated into a practical healthcare-focused web environment with secure file handling, role-based access control, clinical workflow support, prediction history, report generation, and scalable backend design.

This system is intended for research, academic, and educational use only.

---

## Disclaimer

This project is for **research and educational purposes only**. It is not a substitute for professional medical diagnosis, medical treatment, or clinical decision-making.

Always consult a certified cardiologist or qualified medical professional for clinical advice.

---

## Credits

### Project Lead

**Ashfakur Rahman**
Main Contributor and Project Lead

### Team Members

* Md. Jahurul Islam Reday
* Md. Akash Hossain

### Supervisor

*Md. Solaiman Mia* <br> Assistant Professor, Department of Computer Science and Engineering<br>Green University of Bangladesh
  <br>Email: [solaiman@cse.green.edu.bd](mailto:solaiman@cse.green.edu.bd)</br>

### Project Title

**Anomaly Detection in ECG Signals of Heart Disease Prediction using Deep Learning Techniques**

### Project Type

Research-based deep learning project for ECG signal anomaly detection and heart disease prediction support.

---

## Repository Information

* **GitHub Username:** ashfak-g
* **Repository Name:** ECG-Anomaly-Detection-Heart-Disease-Prediction
* **Repository URL:** https://github.com/ashfak-g/ECG-Anomaly-Detection-Heart-Disease-Prediction

---

## Author

**Ashfakur Rahman**

Main Contributor and Project Lead of **Anomaly Detection in ECG Signals of Heart Disease Prediction using Deep Learning Techniques**.
