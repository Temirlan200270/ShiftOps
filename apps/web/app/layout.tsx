import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";

import { Toaster } from "@/components/ui/toaster";
import { TelegramBootstrap } from "@/components/telegram-bootstrap";

import "./globals.css";

// Force dynamic rendering for the entire app: `next-intl` reads the locale
// from cookies/headers, which forbids static prerendering. As a Telegram Web
// App, every request is authenticated and personalised anyway — there is no
// value in attempting to ship static HTML.
export const dynamic = "force-dynamic";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "ShiftOps",
  description: "HoReCa shift control inside Telegram",
};

export const viewport: Viewport = {
  themeColor: "#0E1422",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  return (
    <html lang={locale} className={`dark ${inter.variable}`}>
      <head>
        {/* Telegram WebApp script — required so window.Telegram.WebApp exists. */}
        <script src="https://telegram.org/js/telegram-web-app.js" defer />
      </head>
      <body className="bg-background text-foreground min-h-screen">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <TelegramBootstrap>{children}</TelegramBootstrap>
          <Toaster />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
