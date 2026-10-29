// Multi-channel alerting with Discord primary, email fallback
export async function sendAlert(message: string): Promise<{
  channel: "discord" | "email" | "none";
  success: boolean;
  error?: string;
}> {
  // Try Discord first
  const discordWebhook = process.env.DISCORD_WEBHOOK_FLOW_ALERTS;
  
  if (discordWebhook) {
    try {
      const discordRes = await fetch(discordWebhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          embeds: [{
            title: "🔴 Flow Feed Alert",
            description: message,
            color: 0xFF0000,
            timestamp: new Date().toISOString(),
            footer: { text: "JARVIS Flow Monitor" }
          }]
        })
      });
      
      if (discordRes.ok) {
        return { channel: "discord", success: true };
      }
      
      console.warn("[alerting] Discord webhook failed:", discordRes.status, await discordRes.text());
    } catch (discordError) {
      console.error("[alerting] Discord webhook error:", discordError);
    }
  }
  
  // Fallback to email via Resend
  const resendApiKey = process.env.RESEND_API_KEY;
  const alertEmail = process.env.ALERT_EMAIL;
  
  if (resendApiKey && alertEmail) {
    try {
      const emailRes = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${resendApiKey}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          from: "alerts@jarvis-trader.com",
          to: alertEmail,
          subject: "JARVIS Flow Alert (Discord Failed)",
          text: `${message}\n\n(This alert was sent via email because Discord webhook failed)`
        })
      });
      
      if (emailRes.ok) {
        console.log("[alerting] Email fallback succeeded");
        return { channel: "email", success: true };
      }
      
      const emailError = await emailRes.text();
      console.error("[alerting] Email fallback failed:", emailRes.status, emailError);
      return { channel: "none", success: false, error: emailError };
    } catch (emailError) {
      console.error("[alerting] Email API error:", emailError);
      return { channel: "none", success: false, error: String(emailError) };
    }
  }
  
  console.error("[alerting] No alerting channel configured (Discord or email)");
  return { channel: "none", success: false, error: "No alerting channel configured" };
}
