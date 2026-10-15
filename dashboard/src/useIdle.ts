import { useEffect } from 'react';

const EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;

export function useIdle(ms: number, onIdle: () => void): void {
  useEffect(() => {
    let timer = window.setTimeout(onIdle, ms);
    const reset = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(onIdle, ms);
    };
    EVENTS.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    return () => {
      window.clearTimeout(timer);
      EVENTS.forEach((e) => window.removeEventListener(e, reset));
    };
  }, [ms, onIdle]);
}
