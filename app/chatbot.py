import os
import markdown
import re
from flask import current_app
from typing import Dict, Any

class ChatBot:
    def __init__(self):
        self.client = None
        self.user_chats: Dict[str, Any] = {}

    def _initialize(self):
        if self.client:
            return
            
        gemini_key = os.environ.get('GEMINI_API_KEY') or current_app.config.get('GEMINI_API_KEY')
        if gemini_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=gemini_key)
                return
            except Exception as e:
                print(f"Warning: Failed to initialise new google.genai client: {e}")
                
        print('Warning: GEMINI_API_KEY not found or Gemini client failed. Chatbot will be offline.')

    def _get_user_context(self, user):
        """Generate a personalized context string based on the user's data"""
        context = (
            "You are Dr. AI, a virtual medical assistant for the Heart Anomalies application. "
            "Help users understand ECG terms briefly and empathetically. You are not a doctor and cannot provide diagnoses. "
            "When appropriate, format output with Markdown, bold text, and use lists. "
            "If results are abnormal or medical attention is needed, advise consulting a cardiologist and direct them to click the [Find Medical Help](/medical-help) feature.\n\n"
        )
        
        if not user or not user.is_authenticated:
            return context

        context += f"The user you are speaking to is named {user.name}.\n"
        
        if user.medical_info:
            mi = user.medical_info
            context += "Patient Medical Profiles:\n"
            if mi.age: context += f"- Age: {mi.age}\n"
            if mi.gender: context += f"- Gender: {mi.gender}\n"
            if mi.blood_pressure: context += f"- Blood Pressure: {mi.blood_pressure}\n"
            
        # Check recent predictions for context
        if getattr(user, 'predictions', None) and len(user.predictions) > 0:
            recent_pred = user.predictions[-1]
            context += f"\nThe user recently received a Heart ECG Analysis prediction which resulted in: '{recent_pred.result}'. "
            if recent_pred.result == 'Abnormal':
                context += "Because it is Abnormal, if the user asks about their recent report, show empathy, briefly explain it indicates a possible anomaly, and strongly urge them to visit a doctor using the [Find Medical Help](/medical-help) directory."
            elif recent_pred.result == 'Normal':
                context += "Because it is Normal, you can reassure them their latest ECG scan looks healthy, but to always consult a doctor if they feel unwell."

        return context

    def get_response(self, user_input, current_user=None):
        self._initialize()
        if not self.client:
            return "I apologize, but I am currently offline. Please configure GEMINI_API_KEY to enable the chatbot."

        user_id = str(current_user.id) if (current_user and current_user.is_authenticated) else "anonymous"

        try:
            # Create a chat session per user if it doesn't exist
            if user_id not in self.user_chats:
                system_instruction = self._get_user_context(current_user)
                # Note: google-genai sets system instructions via config 
                from google import genai
                config = genai.types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7 
                )
                chat = self.client.chats.create(
                    model='gemini-2.5-flash',
                    config=config
                )
                self.user_chats[user_id] = chat

            chat = self.user_chats[user_id]
            response = chat.send_message(user_input)
            
            # Simple conversion of markdown links and bold formatting to HTML if needed by frontend
            # Assuming the frontend renders basic HTML or handles markdown
            # The base frontend will use innerHTML if we format it as strong and anchors, let's parse basic markdown.
            html_response = markdown.markdown(response.text)
            
            # We enforce removing outer paragraph if it's just one, to keep chat tight
            if html_response.startswith("<p>") and html_response.endswith("</p>") and html_response.count("<p>") == 1:
                html_response = html_response[3:-4]

            return html_response
            
        except Exception as e:
            print(f"Gemini API Error: {e}")
            return "I apologize, but I'm having trouble connecting to the chatbot service right now. Please try again later."
