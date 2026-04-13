"use client";

import { useMemo, useState } from "react";
import { UploadCloud } from "lucide-react";

import { cn } from "@/lib/utils";

interface FileDropInputProps {
  name: string;
  accept?: string;
}

export function FileDropInput({ name, accept }: FileDropInputProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  const description = useMemo(() => {
    return fileName ?? "Drop a CSV or PDF bank statement here, or click to browse.";
  }, [fileName]);

  return (
    <label
      className={cn(
        "flex min-h-40 cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/30 px-6 py-8 text-center transition-colors",
        isDragging && "border-primary bg-primary/5"
      )}
      onDragEnter={() => setIsDragging(true)}
      onDragLeave={() => setIsDragging(false)}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDrop={() => setIsDragging(false)}
    >
      <UploadCloud className="h-8 w-8 text-primary" />
      <div className="space-y-1">
        <p className="text-sm font-medium">Upload statement file</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <input
        className="hidden"
        type="file"
        name={name}
        accept={accept}
        onChange={(event) => setFileName(event.currentTarget.files?.[0]?.name ?? null)}
      />
    </label>
  );
}