import React, { useState } from "react";

function OCRUploader() {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setLoading(true);

    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch("http://localhost:8000/extract", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();

    setText(data.text);
    setLoading(false);
  };

  return (
    <div className="w-full max-w-xl">
      <input
        type="file"
        accept="application/pdf"
        onChange={handleUpload}
        className="block w-full border border-gray-300 rounded-lg p-2 mb-4"
      />
      {loading && <p className="text-blue-600">Processing PDF...</p>}
      {text && (
        <textarea
          className="w-full h-96 border rounded-md p-3 text-gray-800 bg-white"
          value={text}
          readOnly
        />
      )}
    </div>
  );
}

export default OCRUploader;
