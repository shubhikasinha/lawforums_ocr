import React from "react";
import OCRUploader from "./components/OCRUploader";

function App() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-6">
      <h1 className="text-3xl font-bold mb-4 text-gray-800">
        Offline PDF OCR Extractor
      </h1>
      <p className="text-gray-600 mb-6">
        Upload a PDF (text-based or scanned) and extract clean text instantly.
      </p>
      <OCRUploader />
    </div>
  );
}

export default App;
