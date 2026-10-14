// Every visible UI string, keyed by language. Phase 2 adds 'si' and 'ta' here.
// Spoken lines (greeting, goodbye) come from kiosk-core, not from this file.
export const STRINGS = {
  en: {
    listening: "I'm listening…",
    privacy: 'Camera checks presence only. No photos or video are saved.',
    privacyOff: 'Camera unavailable. Tap to talk to start.',
    talk: 'Tap to talk',
    stop: 'Stop',
    kids: 'Kids mode',
    menuTitle: 'Pick a question',
    menuClose: 'Close',
    prompt: 'Come closer and say Hello!',
    ticker: [
      "Ask me about IIT's degree programmes and campus life.",
      'Curious about research at IIT? Just ask.',
      'LeapGen helps students turn ideas into real startups.',
    ],
    journey: ['Idea', 'Validate', 'Build', 'Launch'],
  },
};

const lang = 'en';

export function t(key) {
  return STRINGS[lang][key] ?? STRINGS.en[key];
}
