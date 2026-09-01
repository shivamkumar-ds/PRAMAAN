import { useState, type FormEvent } from "react";
import { ArrowRight, Headphones, Mail, MessageSquare, Send, ShieldCheck } from "lucide-react";
import { submitContactForm } from "../../api/endpoints";
import { extractErrorMessage } from "../../api/client";
import { useToast } from "../../context/ToastContext";
import { Button, Input, Select } from "../kit";

// Contact channel used everywhere else on the site. Deliberately not
// inventing a phone number or a registered office address here -- neither
// exists to publish honestly yet, so those two items from the reference
// layout are left out rather than fabricated.
const CONTACT_EMAIL = "team.pramaan@gmail.com";
const DEMO_MAILTO = "mailto:" + CONTACT_EMAIL + "?subject=" + encodeURIComponent("Demo request — PRAMAAN");

const contactMethods = [
  {
    icon: Mail,
    color: { bg: "bg-blue-50", text: "text-blue-600" },
    title: "Email Us",
    body: (
      <a href={"mailto:" + CONTACT_EMAIL} className="text-sm text-primary hover:underline">
        {CONTACT_EMAIL}
      </a>
    ),
  },
  {
    icon: Headphones,
    color: { bg: "bg-violet-50", text: "text-violet-600" },
    title: "Request a Demo",
    body: (
      <div>
        <p className="text-sm text-muted-foreground">See PRAMAAN in action with a personalized walkthrough.</p>
        <a
          href={DEMO_MAILTO}
          className="text-sm font-medium text-primary hover:underline inline-flex items-center gap-1 mt-1"
        >
          Book a Demo <ArrowRight size={13} />
        </a>
      </div>
    ),
  },
];

const initialForm = {
  fullName: "",
  workEmail: "",
  companyName: "",
  jobTitle: "",
  phone: "",
  subject: "",
  message: "",
  // Honeypot -- a real visitor never sees or fills this (visually hidden
  // below, not just `type="hidden"`, since some bots skip those). Left
  // non-empty on submit, the backend silently discards the request
  // without persisting it or sending any email. See ContactRequest in
  // backend/app/schemas/contact.py.
  website: "",
};

export function ContactSection() {
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const { notify } = useToast();

  function update<K extends keyof typeof initialForm>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await submitContactForm({
        full_name: form.fullName,
        work_email: form.workEmail,
        company_name: form.companyName || null,
        job_title: form.jobTitle || null,
        phone: form.phone || null,
        subject: form.subject,
        message: form.message,
        website: form.website,
      });
      notify("success", "Thanks for reaching out — we'll be in touch shortly.");
      setForm(initialForm);
    } catch (err) {
      notify("error", extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section id="contact" className="bg-background">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid lg:grid-cols-2 gap-10 items-start">
          {/* Left: intro + contact methods */}
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
              <MessageSquare size={12} />
              Get in Touch
            </span>
            <h2 className="mt-4 text-3xl lg:text-4xl font-bold tracking-tight leading-[1.08] text-foreground">
              We're Here to Help
            </h2>
            <p className="mt-3 text-sm text-muted-foreground leading-relaxed max-w-md">
              Have questions about PRAMAAN? Want to see it in action? Our team is ready to help you make confident
              procurement decisions.
            </p>

            <div className="mt-8 divide-y divide-border border-t border-border">
              {contactMethods.map((m) => (
                <div key={m.title} className="flex items-start gap-4 py-4">
                  <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${m.color.bg} ${m.color.text}`}>
                    <m.icon size={18} />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">{m.title}</p>
                    <div className="mt-0.5">{m.body}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: message form */}
          <div className="rounded-2xl border border-border bg-surface shadow-elevated p-6 lg:p-8">
            <h3 className="text-lg font-bold tracking-tight text-foreground">Send Us a Message</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Fill out the form below and our team will get back to you shortly.
            </p>

            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              <div className="grid sm:grid-cols-2 gap-4">
                <Input
                  label="Full Name *"
                  required
                  placeholder="Enter your full name"
                  value={form.fullName}
                  onChange={(e) => update("fullName", e.target.value)}
                />
                <Input
                  label="Work Email *"
                  type="email"
                  required
                  placeholder="Enter your work email"
                  value={form.workEmail}
                  onChange={(e) => update("workEmail", e.target.value)}
                />
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <Input
                  label="Company Name"
                  placeholder="Enter your company name"
                  value={form.companyName}
                  onChange={(e) => update("companyName", e.target.value)}
                />
                <Input
                  label="Job Title"
                  placeholder="Enter your job title"
                  value={form.jobTitle}
                  onChange={(e) => update("jobTitle", e.target.value)}
                />
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <Input
                  label="Phone Number"
                  type="tel"
                  placeholder="Enter your phone number"
                  value={form.phone}
                  onChange={(e) => update("phone", e.target.value)}
                />
                <Select
                  label="Subject *"
                  required
                  value={form.subject}
                  onChange={(e) => update("subject", e.target.value)}
                >
                  <option value="">Select a subject</option>
                  <option value="General Inquiry">General Inquiry</option>
                  <option value="Request a Demo">Request a Demo</option>
                  <option value="Sales">Sales</option>
                  <option value="Support">Support</option>
                  <option value="Partnership">Partnership</option>
                </Select>
              </div>

              <label className="block">
                <span className="text-xs font-medium text-foreground/90 mb-1.5 block">Message *</span>
                <textarea
                  required
                  rows={4}
                  placeholder="How can we help you?"
                  value={form.message}
                  onChange={(e) => update("message", e.target.value)}
                  className="block w-full rounded-md border border-input bg-surface px-3 py-2 text-sm placeholder:text-muted-foreground/70 focus:outline-none focus:ring-2 focus:ring-ring focus:border-ring transition-shadow resize-none"
                />
              </label>

              {/* Honeypot -- visually hidden (not type="hidden", which
                  some bots skip), unreachable by keyboard tab order, and
                  never announced to assistive tech. A real visitor never
                  interacts with this; see the `website` field's docstring
                  in api/types.ts. */}
              <label className="absolute w-px h-px overflow-hidden opacity-0 pointer-events-none" aria-hidden="true">
                Leave this field empty
                <input
                  type="text"
                  name="website"
                  tabIndex={-1}
                  autoComplete="off"
                  value={form.website}
                  onChange={(e) => update("website", e.target.value)}
                />
              </label>

              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ShieldCheck size={13} className="text-primary shrink-0" />
                We respect your privacy. Your details are used only to respond to your message.
              </p>

              <Button type="submit" size="lg" className="w-full" loading={submitting} icon={<Send size={15} />}>
                Send Message
              </Button>
            </form>
          </div>
        </div>
      </div>
    </section>
  );
}
