"use client";

import { useState, useCallback } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { soundAlertManager } from "@/lib/sound-alerts";

interface SoundControlProps {
  className?: string;
}

export function SoundControl({ className = "" }: SoundControlProps) {
  const [isMuted, setIsMuted] = useState(soundAlertManager.getMuted());
  const [volume, setVolume] = useState(soundAlertManager.getVolume());

  const handleToggleMute = useCallback(() => {
    const newMuted = soundAlertManager.toggleMute();
    setIsMuted(newMuted);
  }, []);

  const handleVolumeChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const newVolume = parseFloat(e.target.value);
    soundAlertManager.setVolume(newVolume);
    setVolume(newVolume);
  }, []);

  return (
    <div className={`flex items-center gap-2 rounded-lg bg-muted/40 px-3 py-2 ${className}`}>
      {/* Mute toggle */}
      <button
        onClick={handleToggleMute}
        aria-label={isMuted ? "Unmute sound alerts" : "Mute sound alerts"}
        className="flex items-center justify-center p-1 rounded hover:bg-muted/60 transition-colors ring-offset-2 focus-visible:ring-2 focus-visible:ring-accent"
        title={isMuted ? "Click to unmute" : "Click to mute"}
      >
        {isMuted ? (
          <VolumeX className="h-4 w-4 text-muted-foreground" />
        ) : (
          <Volume2 className="h-4 w-4 text-foreground" />
        )}
      </button>

      {/* Volume slider */}
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        value={volume}
        onChange={handleVolumeChange}
        disabled={isMuted}
        aria-label="Sound alert volume"
        className="w-24 h-1.5 rounded-lg bg-muted appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed accent-accent"
        style={{
          background: isMuted
            ? "hsl(222 47% 15%)"
            : `linear-gradient(to right, hsl(var(--accent)) 0%, hsl(var(--accent)) ${volume * 100}%, hsl(222 47% 15%) ${volume * 100}%, hsl(222 47% 15%) 100%)`,
        }}
      />

      {/* Volume percentage display */}
      <span className="text-xs font-mono text-muted-foreground w-7 text-right">
        {isMuted ? "—" : `${Math.round(volume * 100)}`}
      </span>
    </div>
  );
}
