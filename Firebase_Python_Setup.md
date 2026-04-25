# Firebase Setup for Python (Admin SDK)

To enable the backend to communicate with Firebase, follow these steps:

## 1. Generate Service Account Key
1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Navigate to **Project Settings > Service Accounts**.
3. Click **Generate New Private Key**.
4. Save the downloaded `.json` file as `serviceAccountKey.json` in the root directory of this project.

## 2. Enable Firestore
1. Go to **Build > Firestore Database**.
2. Click **Create Database**.
3. Use the following collection names:
   - `users`: Stores user profiles and points.
   - `reward_codes`: Stores valid alphanumeric codes.
   - `transactions`: Stores history of redemptions.

## 3. Python Integration Logic
The `app.py` is configured to use `firebase-admin`. It will automatically use the credentials from `serviceAccountKey.json` to authenticate requests.

## 4. Security Rules
Ensure your Firestore rules allow the service account (which has administrative access) to perform operations. For client-side previews, you can use:
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if false; // Only Admin SDK (Python) can access
    }
  }
}
```
