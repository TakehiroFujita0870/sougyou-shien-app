begin;

alter table public.ideas add column title text;
alter table public.ideas add column idea_summary text;

update public.ideas
set
  title = left(pain_statement, 80),
  idea_summary = pain_statement
where title is null or idea_summary is null;

alter table public.ideas alter column title set not null;
alter table public.ideas alter column idea_summary set not null;

alter table public.ideas
  add constraint ideas_title_length
  check (char_length(btrim(title)) between 1 and 80);

alter table public.ideas
  add constraint ideas_summary_length
  check (char_length(btrim(idea_summary)) between 1 and 1000);

grant update (title, idea_summary, pain_statement) on public.ideas to authenticated;

commit;
