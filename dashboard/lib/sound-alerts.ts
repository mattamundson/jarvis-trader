"use strict";

/**
 * SoundAlertManager
 * Uses Web Audio API to generate audio cues for trading alerts
 * No external audio files needed — pure oscillator synthesis
 */

export class SoundAlertManager {
  private audioContext: AudioContext | null = null;
  private isMuted: boolean = false;
  private volume: number = 0.3;

  constructor() {
    // Lazy-init AudioContext on first use
  }

  /**
   * Initialize the AudioContext (called lazily on first sound)
   */
  private initAudioContext(): AudioContext {
    if (!this.audioContext) {
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    }
    return this.audioContext;
  }

  /**
   * Play a single tone
   */
  private playTone(frequency: number, duration: number): Promise<void> {
    return new Promise((resolve) => {
      try {
        const ctx = this.initAudioContext();

        // Resume context if suspended
        if (ctx.state === "suspended") {
          ctx.resume().catch(() => {
            /* ignore */
          });
        }

        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.frequency.value = frequency;
        osc.type = "sine";

        // Fade in and out to avoid clicks
        const startTime = ctx.currentTime;
        const fadeInTime = Math.min(duration * 0.1, 0.01);
        const fadeOutTime = Math.min(duration * 0.1, 0.01);

        gain.gain.setValueAtTime(0, startTime);
        gain.gain.linearRampToValueAtTime(this.isMuted ? 0 : this.volume, startTime + fadeInTime);
        gain.gain.setValueAtTime(this.isMuted ? 0 : this.volume, startTime + duration - fadeOutTime);
        gain.gain.linearRampToValueAtTime(0, startTime + duration);

        osc.start(startTime);
        osc.stop(startTime + duration);

        setTimeout(resolve, duration * 1000);
      } catch (e) {
        console.warn("Sound alert error:", e);
        resolve();
      }
    });
  }

  /**
   * Trade Signal: 2 ascending tones (440Hz → 660Hz)
   * Indicates BUY/SELL signal with positive confirmation
   */
  async tradeSignal(): Promise<void> {
    if (this.isMuted) return;

    await this.playTone(440, 0.1);
    await new Promise((resolve) => setTimeout(resolve, 50));
    await this.playTone(660, 0.1);
  }

  /**
   * Kill Switch Alert: 3 rapid descending tones
   * Urgent warning when kill switch is activated
   */
  async killSwitchAlert(): Promise<void> {
    if (this.isMuted) return;

    await this.playTone(880, 0.1);
    await new Promise((resolve) => setTimeout(resolve, 50));
    await this.playTone(440, 0.1);
    await new Promise((resolve) => setTimeout(resolve, 50));
    await this.playTone(220, 0.1);
  }

  /**
   * Circuit Breaker Warning: single 660Hz tone
   * Alert when circuit breakers are triggered
   */
  async circuitBreakerWarning(): Promise<void> {
    if (this.isMuted) return;

    await this.playTone(660, 0.2);
  }

  /**
   * Order Fill: single 880Hz tone
   * Confirmation that an order has been filled
   */
  async orderFill(): Promise<void> {
    if (this.isMuted) return;

    await this.playTone(880, 0.1);
  }

  /**
   * Error Alert: low 220Hz tone
   * Something went wrong or needs attention
   */
  async error(): Promise<void> {
    if (this.isMuted) return;

    await this.playTone(220, 0.3);
  }

  /**
   * Toggle mute state
   */
  toggleMute(): boolean {
    this.isMuted = !this.isMuted;
    return this.isMuted;
  }

  /**
   * Check if currently muted
   */
  getMuted(): boolean {
    return this.isMuted;
  }

  /**
   * Set mute state directly
   */
  setMuted(muted: boolean): void {
    this.isMuted = muted;
  }

  /**
   * Set volume (0.0 to 1.0)
   */
  setVolume(vol: number): void {
    this.volume = Math.max(0, Math.min(1, vol));
  }

  /**
   * Get current volume
   */
  getVolume(): number {
    return this.volume;
  }
}

/**
 * Global singleton instance
 */
export const soundAlertManager = new SoundAlertManager();
