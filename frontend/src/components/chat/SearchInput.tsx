"use client";

import { useState, useRef, useCallback, useEffect, KeyboardEvent } from "react";
import { Send, Loader2, MapPin, Mic, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { transcribe } from "@/lib/api";

interface SearchInputProps {
  onSubmit: (query: string) => void;
  onCancel?: () => void;
  isLoading?: boolean;
  placeholder?: string;
  initialValue?: string;
  onInitialValueConsumed?: () => void;
}

export default function SearchInput({
  onSubmit,
  onCancel,
  isLoading = false,
  placeholder = 'Ask LocalLens anything… "Best ramen near downtown Seattle"',
  initialValue = "",
  onInitialValueConsumed,
}: SearchInputProps) {
  const [value, setValue] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    if (isRecording || isLoading) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (blob.size === 0) return;
        setIsTranscribing(true);
        try {
          const text = await transcribe(blob);
          if (text) {
            setValue((v) => (v ? `${v} ${text}` : text));
            textareaRef.current?.focus();
          }
        } catch (err) {
          console.warn("Transcription error:", err);
        } finally {
          setIsTranscribing(false);
        }
      };
      recorderRef.current = rec;
      rec.start();
      setIsRecording(true);
    } catch (err) {
      console.warn("Could not start recording:", err);
    }
  }, [isRecording, isLoading]);

  const stopRecording = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
    setIsRecording(false);
  }, []);

  // Allow parent to inject a value (e.g., clicking suggested query)
  useEffect(() => {
    if (initialValue) {
      setValue(initialValue);
      onInitialValueConsumed?.();
      textareaRef.current?.focus();
    }
  }, [initialValue, onInitialValueConsumed]);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, isLoading, onSubmit]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    // Auto-resize
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  };

  return (
    <div className="relative">
      {/* here add a PromptToolBar component with a button to add a new chat, align it to the right with modern design */}
      {/* Gradient fade above input */}
      <div className="absolute -top-8 left-0 right-0 h-8 bg-gradient-to-t from-surface-deep to-transparent pointer-events-none" />
      <div
        className={cn(
          "flex items-center  gap-3 p-3 rounded-2xl",
          "bg-surface-card border border-surface-border",
          "focus-within:border-brand/60 focus-within:shadow-lg focus-within:shadow-brand/10",
          "transition-all duration-200",
          isLoading && "opacity-80",
        )}
      >
        <div className="flex items-center gap-2 px-1 py-1 text-brand flex-shrink-0 self-center">
          <MapPin size={24} />
        </div>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading}
          rows={1}
          className={cn(
            "flex-1 bg-transparent text-slate-100 placeholder-slate-600 text-sm",
            "resize-none outline-none leading-relaxed",
            "min-h-[36px] max-h-[160px] py-1.5",
            "disabled:cursor-not-allowed",
          )}
        />
        {/* Mic — push-to-talk: click to start, click again to stop & transcribe */}
        <button
          type="button"
          onClick={isRecording ? stopRecording : startRecording}
          disabled={isLoading || isTranscribing}
          aria-label={isRecording ? "Stop recording" : "Start voice input"}
          className={cn(
            "flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center",
            "transition-all duration-200 relative",
            isRecording
              ? "bg-red-500/90 text-white shadow-md shadow-red-500/40 animate-pulse"
              : "bg-surface-DEFAULT text-slate-400 hover:text-slate-200 hover:bg-surface-hover",
            (isLoading || isTranscribing) && "opacity-50 cursor-not-allowed",
          )}
        >
          {isTranscribing ? (
            <Loader2 size={15} className="animate-spin" />
          ) : isRecording ? (
            <Square size={13} fill="currentColor" />
          ) : (
            <Mic size={15} />
          )}
        </button>

        <button
          onClick={isLoading ? onCancel : handleSubmit}
          disabled={isLoading ? !onCancel : !value.trim()}
          className={cn(
            "flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center",
            "transition-all duration-200",
            isLoading
              ? "bg-red-500/90 hover:bg-red-500 text-white shadow-md shadow-red-500/30"
              : value.trim()
              ? "bg-brand hover:bg-brand-dark text-white shadow-md shadow-brand/30 hover:scale-105 active:scale-95"
              : "bg-surface-DEFAULT text-slate-600 cursor-not-allowed",
          )}
          aria-label={isLoading ? "Stop search" : "Send message"}
        >
          {isLoading ? (
            <Square size={13} fill="currentColor" />
          ) : (
            <Send size={15} />
          )}
        </button>
      </div>
      <p className="text-center text-xs text-slate-700 mt-2">
        Press Enter to search · Shift+Enter for new line
      </p>
    </div>
  );
}
