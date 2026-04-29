import { useEffect, useState } from "react";
import { collection, query, onSnapshot, doc, updateDoc } from "firebase/firestore";
import { db, vertexAI } from "../lib/firebase";
import { getGenerativeModel } from "firebase/vertexai";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface VaultNote {
  id: string;
  source_filename: string;
  status: "Needs Review" | "Reviewed" | "Exported";
  markdown_content: string;
  metadata?: any;
}

export default function VaultPage() {
  const [notes, setNotes] = useState<VaultNote[]>([]);
  const [selectedNote, setSelectedNote] = useState<VaultNote | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    const q = query(collection(db, "ocr_staging_vault"));
    const unsubscribe = onSnapshot(q, (snapshot) => {
      const results: VaultNote[] = [];
      snapshot.forEach((doc) => {
        results.push({ id: doc.id, ...doc.data() } as VaultNote);
      });
      setNotes(results);
    });
    return unsubscribe;
  }, []);

  const handleSelect = (note: VaultNote) => {
    setSelectedNote(note);
    setEditMode(false);
    setDraftContent(note.markdown_content);
  };

  const saveChanges = async () => {
    if (!selectedNote) return;
    setIsProcessing(true);
    try {
      const docRef = doc(db, "ocr_staging_vault", selectedNote.id);
      await updateDoc(docRef, {
        markdown_content: draftContent,
        status: "Reviewed"
      });
      setEditMode(false);
    } catch (e) {
      console.error(e);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleApproveAndParse = async () => {
    if (!selectedNote) return;
    setIsProcessing(true);
    try {
      // Step 1: Use Vertex AI to parse markdown to schema
      const model = getGenerativeModel(vertexAI, { model: "gemini-2.5-flash" });
      const prompt = `Parse the following markdown text into structured JSON format appropriate for our transaction tables. If it's a sales ledger, return {"type": "sales", "data": <array-of-entries>}. If it's a stock check, return {"type": "stock", "data": <array-of-items>}. Here is the markdown:\n\n${draftContent}`;
      
      const result = await model.generateContent(prompt);
      const response = await result.response;
      let text = response.text();
      // clean backticks from text if gemini responded with ```json
      if (text.startsWith('```json')) text = text.slice(7, -3);
      if (text.startsWith('```')) text = text.slice(3, -3);
      
      const parsedJson = JSON.parse(text);
      
      // Step 2: Send to backend
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000/api";
      const res = await fetch(`${apiUrl}/v1/ingest/vault-document`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: selectedNote.id,
          payload: parsedJson
        })
      });

      if (res.ok) {
        const docRef = doc(db, "ocr_staging_vault", selectedNote.id);
        await updateDoc(docRef, { status: "Exported" });
        setNotice({ tone: "success", message: "Exported successfully to Snowflake." });
      } else {
        setNotice({ tone: "error", message: "Failed to export to Snowflake." });
      }
    } catch (e) {
      console.error(e);
      setNotice({ tone: "error", message: "Error approving document." });
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="flex h-full bg-slate-900 border-t border-slate-800">
      {/* Sidebar ListView */}
      <div className="w-1/4 min-w-[250px] border-r border-slate-800 overflow-y-auto">
        <div className="p-4 bg-slate-800 font-bold text-slate-200 sticky top-0 border-b border-slate-700">
          Staging Vault
        </div>
        <ul>
          {notes.map(note => (
            <li 
              key={note.id}
              onClick={() => handleSelect(note)}
              className={`p-3 cursor-pointer border-b border-slate-800 hover:bg-slate-800 transition-colors ${selectedNote?.id === note.id ? 'bg-indigo-900 bg-opacity-30 border-l-4 border-l-indigo-500' : ''}`}
            >
              <div className="font-semibold text-slate-300 truncate">{note.source_filename}</div>
              <div className="text-xs mt-1">
                <span className={`px-2 py-0.5 rounded-full ${note.status === 'Needs Review' ? 'bg-amber-900/40 text-amber-500' : note.status === 'Reviewed' ? 'bg-blue-900/40 text-blue-400' : 'bg-emerald-900/40 text-emerald-400'}`}>
                  {note.status}
                </span>
              </div>
            </li>
          ))}
          {notes.length === 0 && (
            <div className="p-4 text-slate-500 text-sm italic">No items in staging.</div>
          )}
        </ul>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden bg-slate-900">
        {selectedNote ? (
          <>
            <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-900 shadow-sm">
              <div className="min-w-0">
                <h2 className="truncate text-lg font-bold text-slate-100">{selectedNote.source_filename}</h2>
                {notice && (
                  <p className={notice.tone === "success" ? "mt-1 text-xs text-emerald-400" : "mt-1 text-xs text-red-400"}>
                    {notice.message}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-3">
                {editMode ? (
                  <>
                    <button onClick={() => setEditMode(false)} className="px-3 py-1.5 text-sm bg-slate-800 text-slate-300 rounded hover:bg-slate-700 transition">Cancel</button>
                    <button onClick={saveChanges} disabled={isProcessing} className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-500 transition shadow disabled:opacity-50">
                      {isProcessing ? "Saving..." : "Save Edits"}
                    </button>
                  </>
                ) : (
                  <>
                    <button onClick={() => setEditMode(true)} className="px-3 py-1.5 text-sm bg-slate-800 text-slate-300 rounded hover:bg-slate-700 transition">Edit</button>
                    <button onClick={handleApproveAndParse} disabled={isProcessing || selectedNote.status === "Exported"} className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded hover:bg-emerald-500 transition shadow flex items-center space-x-1 disabled:opacity-50">
                      <span>{isProcessing ? "Vertex Parsing..." : "Approve & Push"}</span>
                    </button>
                  </>
                )}
              </div>
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 bg-slate-950 text-slate-300">
              {editMode ? (
                <textarea
                  className="w-full h-full bg-slate-900 text-slate-200 p-4 font-mono text-sm border-0 focus:ring-2 focus:ring-indigo-500 rounded resize-none"
                  value={draftContent}
                  onChange={(e) => setDraftContent(e.target.value)}
                />
              ) : (
                <div className="prose prose-invert prose-indigo max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {selectedNote.markdown_content}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-slate-500">
            Select a document from the vault to review
          </div>
        )}
      </div>
    </div>
  );
}
