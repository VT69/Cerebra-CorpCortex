"use client";

import { useState, useRef } from "react";
import { Upload, X, File, AlertCircle, CheckCircle2 } from "lucide-react";
import { ingestDocument } from "@/lib/api";

export function UploadModal({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setStatus("idle");
      setMessage("");
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    setStatus("uploading");

    try {
      const data = await ingestDocument(file, "generic");

      if (data.status === "skipped") {
        setStatus("success");
        setMessage("Document already exists in the knowledge base (fingerprint match).");
      } else if (data.status === "error") {
        setStatus("error");
        setMessage(data.message || "Processing error.");
      } else {
        setStatus("success");
        setMessage(`Successfully processed ${data.chunks} chunks, ${data.nodes} nodes, ${data.edges} edges.`);
      }
    } catch (err: any) {
      console.error(err);
      setStatus("error");
      setMessage(err.message || "Network error occurred.");
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-zinc-900 border border-white/10 rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 bg-black/40">
          <h2 className="font-semibold text-lg text-white">Upload Document</h2>
          <button 
            onClick={onClose}
            className="text-zinc-400 hover:text-white transition-colors"
            disabled={status === "uploading"}
          >
            <X size={20} />
          </button>
        </div>
        
        <div className="p-6">
          {!file ? (
            <div className="flex flex-col gap-4">
              <div 
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed border-zinc-700 hover:border-accent/50 hover:bg-accent/5 transition-all rounded-lg p-8 flex flex-col items-center justify-center cursor-pointer text-center group"
              >
                <Upload className="w-10 h-10 text-zinc-500 group-hover:text-accent mb-4 transition-colors" />
                <p className="text-zinc-300 font-medium mb-1">Click to browse or drag file here</p>
                <p className="text-xs text-zinc-500">Supports PDF, DOCX, CSV, TXT, PNG, JPG</p>
                <input 
                  type="file" 
                  ref={fileInputRef} 
                  onChange={handleFileChange} 
                  className="hidden" 
                  accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg,.jpeg,.eml"
                />
              </div>
              <div className="flex justify-end mt-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-sm font-medium text-zinc-300 hover:text-white"
                >
                  Close
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3 p-4 bg-black/40 border border-white/10 rounded-lg">
                <div className="p-2 bg-accent/20 text-accent rounded">
                  <File size={24} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white truncate">{file.name}</p>
                  <p className="text-xs text-zinc-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                </div>
                {status === "idle" && (
                  <button 
                    onClick={() => setFile(null)}
                    className="text-zinc-500 hover:text-red-400 p-1"
                  >
                    <X size={16} />
                  </button>
                )}
              </div>

              {status === "error" && (
                <div className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
                  <AlertCircle size={16} className="mt-0.5 shrink-0" />
                  <p>{message}</p>
                </div>
              )}

              {status === "success" && (
                <div className="flex items-start gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-400 text-sm">
                  <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
                  <p>{message}</p>
                </div>
              )}

              <div className="flex justify-end gap-3 mt-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-sm font-medium text-zinc-300 hover:text-white"
                  disabled={status === "uploading"}
                >
                  {status === "success" ? "Close" : "Cancel"}
                </button>
                
                {status !== "success" && (
                  <button
                    onClick={handleUpload}
                    disabled={status === "uploading"}
                    className="px-4 py-2 text-sm font-medium bg-accent hover:bg-accent/80 text-white rounded-lg transition-colors flex items-center justify-center min-w-[100px] disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {status === "uploading" ? (
                      <span className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin"></span>
                    ) : (
                      "Upload"
                    )}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
