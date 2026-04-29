import { initializeApp } from "firebase/app";
import type { FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";
import { getFirestore, type Firestore } from "firebase/firestore";
import { getVertexAI, type VertexAI } from "firebase/vertexai";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "victoriaensoapp",
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const requiredConfigKeys = [
  "apiKey",
  "authDomain",
  "projectId",
  "storageBucket",
  "messagingSenderId",
  "appId",
] as const;

export const missingFirebaseConfig = requiredConfigKeys.filter((key) => {
  const value = firebaseConfig[key];
  return typeof value !== "string" || value.trim().length === 0;
});

let appInstance: FirebaseApp | null = null;
let authInstance: Auth | null = null;
let dbInstance: Firestore | null = null;
let vertexAIInstance: VertexAI | null = null;

export let firebaseConfigError = "";

if (missingFirebaseConfig.length > 0) {
  firebaseConfigError = `Missing Firebase web config: ${missingFirebaseConfig.join(", ")}`;
} else {
  try {
    appInstance = initializeApp(firebaseConfig);
    authInstance = getAuth(appInstance);
    dbInstance = getFirestore(appInstance);
    vertexAIInstance = getVertexAI(appInstance);
  } catch (error) {
    firebaseConfigError =
      error instanceof Error ? error.message : "Firebase initialization failed";
  }
}

export const app = appInstance as FirebaseApp;
export const auth = authInstance as Auth;
export const db = dbInstance as Firestore;
export const vertexAI = vertexAIInstance as VertexAI;
