import { useState } from "react";

import { useAction } from "../hooks/useApi";
import { api, relative } from "../services/api";
import { formatWhatsApp, whatsappChatUrl } from "../utils/whatsapp";
import { Alert, Button } from "./ui";

/** Opens the client's WhatsApp chat in a new tab. */
export function WhatsAppChatLink({ name, number, label }: { name: string; number: string; label?: string }) {
  return (
    <a className="btn" href={whatsappChatUrl(number)} target="_blank" rel="noopener noreferrer" aria-label={`Chat with ${name} on WhatsApp`}>
      {label ?? "Chat on WhatsApp"}
    </a>
  );
}

/**
 * Sends a stored report file to the client. WhatsApp cannot take a file from a web page by link, so:
 * - where the device offers a share sheet (phones, Windows, recent Chrome/Edge), the file is shared and the
 *   researcher picks WhatsApp and the client's chat;
 * - otherwise the file is downloaded and the client's chat is opened with a message, to attach the file there.
 */
export function SendReportToClient({ clientName, clientNumber, projectTitle, downloadUrl, filename }: {
  clientName: string;
  clientNumber: string;
  projectTitle: string;
  downloadUrl: string;
  filename: string;
}) {
  const { busy, error, run } = useAction();
  const [note, setNote] = useState<string | null>(null);
  const [chatUrl, setChatUrl] = useState<string | null>(null);
  const message = `Dear ${clientName}, please find attached the report for "${projectTitle}".`;

  const send = () => {
    setNote(null);
    setChatUrl(null);
    run(async () => {
      const blob = await api.blob(relative(downloadUrl));
      const file = new File([blob], filename, { type: blob.type || "application/octet-stream" });
      if (typeof navigator.share === "function" && typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
        try {
          await navigator.share({ files: [file], title: projectTitle, text: message });
          setNote(`Choose WhatsApp in the share menu, then ${clientName}'s chat.`);
        } catch (err) {
          if (!(err instanceof DOMException && err.name === "AbortError")) throw err;
        }
        return;
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setChatUrl(whatsappChatUrl(clientNumber, message));
      setNote(`The report has been downloaded. Open the chat, then attach the downloaded file (${filename}) and send it.`);
    });
  };

  return (
    <div className="stack" style={{ gap: "0.4rem" }}>
      <div className="row">
        <Button small variant="primary" busy={busy} onClick={send} aria-label={`Send to ${clientName} on WhatsApp`}>
          Send to client on WhatsApp
        </Button>
        <span className="small muted">{formatWhatsApp(clientNumber)}</span>
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {note && <Alert kind="ok">{note}</Alert>}
      {chatUrl && (
        <a className="btn small" href={chatUrl} target="_blank" rel="noopener noreferrer">Open the chat with {clientName}</a>
      )}
    </div>
  );
}
