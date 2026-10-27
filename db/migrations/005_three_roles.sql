-- Хэрэглэгчийн үүргийг дипломын Хүснэгт 2.1-ийн дагуу гурав болгоно:
--   executive (удирдлага) — бүх салбар, харах ба экспорт
--   manager   (менежер)   — зөвхөн өөрийн салбар: импорт, чанар, таамаглал, тайлан, экспорт
--   admin     (админ)     — хэрэглэгч, эрх, салбарын оноолт, архив, аудит
-- Хуучин үүрэг: manager(харагч) → executive; data_steward, analyst, researcher → manager.
ALTER TABLE governance.app_user DROP CONSTRAINT IF EXISTS app_user_roles_check;
ALTER TABLE governance.app_user ADD COLUMN IF NOT EXISTS branches text[] NOT NULL DEFAULT '{}';

UPDATE governance.app_user u
   SET roles = ARRAY(SELECT DISTINCT CASE r WHEN 'manager' THEN 'executive' WHEN 'admin' THEN 'admin' ELSE 'manager' END
                       FROM unnest(u.roles) AS r ORDER BY 1);
UPDATE governance.app_user SET branches = '{*}' WHERE 'manager' = ANY(roles) AND branches = '{}';

ALTER TABLE governance.app_user
  ADD CONSTRAINT app_user_roles_check CHECK (roles <@ ARRAY['executive','manager','admin']::text[]);

COMMENT ON COLUMN governance.app_user.branches IS
  'Менежерийн хариуцах салбарын код; ''*'' = бүх салбар. Удирдлага, админд хамаарахгүй.';
