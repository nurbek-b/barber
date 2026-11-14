import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";

import { Button, Card, CardContent, CardHeader, CardTitle, Field, Input } from "@/components/ui";
import { ADMIN, ApiError, api, call } from "@/lib/api";
import { meKey } from "@/lib/auth";

const schema = z.object({
  login: z.string().trim().min(1),
  password: z.string().min(1),
});
type Values = z.infer<typeof schema>;

export default function Login() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { login: "", password: "" },
  });

  const submit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const result = await call(api.POST(`${ADMIN}/auth/login`, { body: values }));
      client.setQueryData(meKey, result.user);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 429) setError(t("auth.tooMany"));
      else if (caught instanceof ApiError && caught.status === 401) setError(t("auth.invalid"));
      else setError(caught instanceof Error ? caught.message : String(caught));
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">✂️ {t("auth.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4" noValidate>
            <Field
              label={t("auth.login")}
              htmlFor="login"
              error={form.formState.errors.login && t("common.required")}
            >
              <Input id="login" autoComplete="username" autoFocus {...form.register("login")} />
            </Field>
            <Field
              label={t("auth.password")}
              htmlFor="password"
              error={form.formState.errors.password && t("common.required")}
            >
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...form.register("password")}
              />
            </Field>
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
              {t("auth.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
