import React, { useState } from "react";

function OCRUploader() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(""); // For user feedback

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setLoading(true);
    setStatus(`Processing ${file.name}...`);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://localhost:8000/extract", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        // Handle HTTP errors (like 500 or 415)
        const errorDetail = (await res.json().catch(() => ({}))).detail;
        throw new Error(errorDetail || `Server error: ${res.status}`);
      }

      // Handle the file download
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "extracted_text.docx"; // The filename you want
      document.body.appendChild(a);
      a.click();

      // Clean up
      a.remove();
      window.URL.revokeObjectURL(url);

      setStatus("Success! Your file has been downloaded.");

    } catch (error) {
      console.error("Upload failed:", error);
      setStatus(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full max-w-xl">
      <input
        type="file"
        // Updated accept attribute to include images
        accept="application/pdf, image/png, image/jpeg, image/bmp, image/webp"
        onChange={handleUpload}
        className="block w-full border border-gray-300 rounded-lg p-2 mb-4"
        disabled={loading} // Disable input while loading
      />
      {status && (
        <p className={`text-sm ${status.startsWith("Error:") ? 'text-red-600' : 'text-blue-600'}`}>
          {status}
        </p>
      )}
      {/* The textarea is no longer needed as the result is a download */}
    </div>
  );
}

export default OCRUploader;