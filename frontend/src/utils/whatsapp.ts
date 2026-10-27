// WhatsApp helpers. wa.me links open the chat with a number directly; the number must be
// digits with the country code and no "+" (the backend stores it in that form).

/** Digits only, as typed by a person: spaces, "+", dashes and brackets are dropped. */
export function normaliseWhatsApp(value: string): string {
  return value.replace(/[\s()+.-]/g, "");
}

/** True when the number has 8 to 15 digits and starts with the country code, not a local leading 0. */
export function isValidWhatsApp(value: string): boolean {
  const digits = normaliseWhatsApp(value);
  return /^[1-9]\d{7,14}$/.test(digits);
}

/** The message for a number that is not valid, or null when it is valid or still empty. */
export function whatsAppProblem(value: string): string | null {
  if (!value.trim() || isValidWhatsApp(value)) return null;
  if (normaliseWhatsApp(value).startsWith("0")) {
    return "Enter the number with the country code, without the leading 0 (for example 237 677 000 000).";
  }
  return "Enter the WhatsApp number with the country code, for example 237 677 000 000.";
}

/** Link that opens the client's WhatsApp chat, optionally with a message already typed in. */
export function whatsappChatUrl(number: string, message?: string): string {
  const base = `https://wa.me/${normaliseWhatsApp(number)}`;
  return message ? `${base}?text=${encodeURIComponent(message)}` : base;
}

/** "237 677 000 000" style, for display only. */
export function formatWhatsApp(number: string): string {
  return `+${normaliseWhatsApp(number)}`;
}
