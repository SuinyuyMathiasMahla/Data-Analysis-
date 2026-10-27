-- =============================================================================
-- Development / test data.  NEVER load this file into a production database.
--
--     mysql -u root -p academic_research < database/seed.sql
--
-- It creates three accounts for local testing. Only Argon2id password HASHES
-- are stored here. The shared development password is documented in
-- README.md ("Development accounts"); change it after first sign-in, or create
-- your own accounts with  python backend/scripts/create_user.py
-- =============================================================================

USE academic_research;

INSERT INTO users (id, email, password_hash, full_name, institution, department, academic_level, is_active, is_email_verified) VALUES
  (1, 'admin@example.org',      '$argon2id$v=19$m=65536,t=3,p=4$FwpLCmg5Fh2mV4tLJ5UqCQ$FyEKbmIKLNw0/rKl1DVWgRi5B/VUBI4MgMMJfEzzbD4',      'Dev Administrator', 'Example University', 'ICT Services', NULL, 1, 1),
  (2, 'supervisor@example.org', '$argon2id$v=19$m=65536,t=3,p=4$SVnGHjRJacLS3mxZxZtcPA$4TFutAJ8gsdEMRm+1nVCzwIpcXDNF/xBxEnToMVySWM', 'Dr. Dev Supervisor', 'Example University', 'Education', NULL, 1, 1),
  (3, 'student@example.org',    '$argon2id$v=19$m=65536,t=3,p=4$N7nFKJyd2w3OqBMkqpcIMQ$AfMuyRYeWz10wgYTR9jzx0WpOyAGxOTPJNsAjk5lwng',    'Dev Student', 'Example University', 'Education', 'masters', 1, 1);

INSERT INTO user_roles (user_id, role_id) VALUES
  (1, 3), (1, 1),      -- admin (+ researcher so the admin can try the workflow)
  (2, 2),              -- supervisor
  (3, 1);              -- researcher

-- A sample project owned by the student account. Upload
-- sample_data/student_performance.csv into it to try the full workflow.
INSERT INTO projects (id, owner_id, title, academic_level, research_field, institution, department, research_problem,
                      general_objective, study_population, sample_size, sampling_technique, research_methodology, study_design,
                      data_collection_method, status) VALUES
  (1, 3, 'Impact of Social Media Use on Academic Performance', 'masters', 'Education', 'Example University', 'Education',
   'Students spend increasing time on social media, and its relationship with academic performance is unclear.',
   'To examine the relationship between social media use and the academic performance of undergraduate students.',
   'Undergraduate students of Example University', 240, 'Convenience sampling', 'Quantitative', 'Cross-sectional survey',
   'Self-administered questionnaire', 'active');

INSERT INTO objectives (project_id, position, text) VALUES
  (1, 0, 'To determine the relationship between daily social media use and GPA.'),
  (1, 1, 'To compare GPA across levels of social media use.'),
  (1, 2, 'To identify which study habits predict GPA.');

INSERT INTO research_questions (id, project_id, code, text, position) VALUES
  (1, 1, 'RQ1', 'Is there a relationship between daily social media use and GPA?', 0),
  (2, 1, 'RQ2', 'Does GPA differ between students with low, moderate and high social media use?', 1),
  (3, 1, 'RQ3', 'Which factors (study hours, social media use, attendance) predict GPA?', 2);

INSERT INTO hypotheses (project_id, research_question_id, code, null_text, alternative_text, direction, alpha) VALUES
  (1, 1, 'H1', 'There is no significant relationship between daily social media use and GPA.',
         'There is a significant relationship between daily social media use and GPA.', 'non_directional', 0.0500),
  (1, 2, 'H2', 'Mean GPA does not differ between levels of social media use.',
         'Mean GPA differs between at least two levels of social media use.', 'non_directional', 0.0500);

INSERT INTO project_members (project_id, user_id, member_role) VALUES
  (1, 2, 'supervisor');

INSERT INTO notifications (user_id, project_id, type, title, body) VALUES
  (3, 1, 'info', 'Welcome', 'Upload sample_data/student_performance.csv to this project to try the full workflow.');
