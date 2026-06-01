from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables BEFORE importing app
print('Loaded DATABASE_URL from environment:', repr(os.environ.get('DATABASE_URL')))

from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
