"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import { UploadModal } from "./UploadModal";

export function HeaderActions() {
  const [showUploadModal, setShowUploadModal] = useState(false);

  return (
    <>
      <button 
        onClick={() => setShowUploadModal(true)}
        className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg transition-colors text-zinc-300 hover:text-white"
      >
        <Upload size={16} />
        Upload Document
      </button>

      {showUploadModal && <UploadModal onClose={() => setShowUploadModal(false)} />}
    </>
  );
}
