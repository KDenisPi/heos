import { Stack, Typography } from "@mui/material";

export function PlaceholderView({ title, text }: { title: string; text: string }) {
  return (
    <Stack spacing={1} sx={{ p: 4 }}>
      <Typography variant="h5">{title}</Typography>
      <Typography color="text.secondary">{text}</Typography>
    </Stack>
  );
}
