import React, { useState } from "react";

function OCRUploader() {
  const [loading, setLoading] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [status, setStatus] = useState("");
  const [text, setText] = useState("");
  const [originalFile, setOriginalFile] = useState(null); // To remember the file for download

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setLoading(true);
    setStatus(`Processing ${file.name}...`);
    setText(""); // Clear old text
    setOriginalFile(null); // Clear old file

    const formData = new FormData();
    formData.append("file", file);

    try {
      // Call the NEW /extract-text endpoint
      const res = await fetch("http://localhost:8000/extract-text", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || `Server error: ${res.status}`);
      }

      // Set the text to display it
      setText(data.text);
      setStatus("Success! Text extracted.");
      // REMEMBER the file so we can download it later
      setOriginalFile(file);

    } catch (error) {
      console.error("Upload failed:", error);
      setStatus(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!originalFile) return;

    setIsDownloading(true);
    setStatus("Preparing download...");

    const formData = new FormData();
    formData.append("file", originalFile);

    try {
      // Call the NEW /extract-docx endpoint
      const res = await fetch("http://localhost:8000/extract-docx", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errorDetail = (await res.json().catch(() => ({}))).detail;
        throw new Error(errorDetail || `Server error: ${res.status}`);
      }

      // The download logic
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "extracted_text.docx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      
      setStatus("Success! File downloaded.");

    } catch (error) {
      console.error("Download failed:", error);
      setStatus(`Error: ${error.message}`);
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="w-full max-w-xl">
      <input
        type="file"
        accept="application/pdf, image/png, image/jpeg, image/bmp, image/webp"
        onChange={handleUpload}
        className="block w-full border border-gray-300 rounded-lg p-2 mb-4"
        disabled={loading || isDownloading} // Disable if busy
      />

      {/* Show status message */}
      {status && (
        <p className={`text-sm mb-2 ${status.startsWith("Error:") ? 'text-red-600' : 'text-blue-600'}`}>
          {status}
        </p>
      )}

      {/* --- NEW DOWNLOAD BUTTON --- */}
      {/* Show this button ONLY if text is ready and we aren't busy */}
      {text && !loading && (
        <button
          onClick={handleDownload}
          disabled={isDownloading}
          className="bg-green-600 text-white px-4 py-2 rounded-md mb-4 disabled:bg-gray-400"
        >
          {isDownloading ? "Downloading..." : "Download as .docx"}
        </button>
      )}
      
      {/* This shows the text with preserved formatting */}
      {text && (
        <textarea
          className="w-full h-96 border rounded-md p-3 text-gray-800 bg-white whitespace-pre-wrap"
          value={text}
          readOnly
        />
      )}
    </div>
  );
}

export default OCRUploader;