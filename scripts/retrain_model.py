from ml.intent_classifier import IntentClassifier

if __name__ == "__main__":
    model = IntentClassifier()
    model.retrain()
    print("Model retrained and saved.")
