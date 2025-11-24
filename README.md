# Family Photo Rater

A tiny Flask app to upload photos and let family members rate each one with 1–5 stars.
Each person’s rating is saved separately (no overwriting others). You can view averages,
count of ratings, and the top images.

## Features

- Upload multiple photos (drag/drop or file picker)
- Simple "What's your name?" prompt saved in browser (localStorage)
- 1–5 star ratings; each user can rate each photo once (and update their own rating)
- Live averages and counts
- Sort by newest, highest average, most ratings
- "Top X" filter
- Works locally; all data stays on your machine
- SQLite database in `instance/family_rater.db`

## Quick start

1. Create & activate a virtual environment (recommended).
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the server:

   ```bash
   python app.py
   ```

4. Open the app:
   - Admin (upload & stats): [localhost:5000/admin](loacalhost:5000/admin)
   - Gallery (family rating page): [localhost:5000/gallery](loacalhost:5000/gallery)

> Tip: Share the `/gallery` link on your home network so family can rate from their own devices.

## Config

- `UPLOAD_FOLDER`: defaults to `uploads/`
- `MAX_CONTENT_LENGTH`: defaults to 30 MB per request
- Allowed file types: `.jpg .jpeg .png .gif .webp`

## Backups

- Your images are in `uploads/`.
- Ratings are in `instance/family_rater.db` (SQLite). Stop the server and copy that file to back up.

## Notes

- This is deliberately simple and meant for home use. For internet-facing use, add auth and HTTPS.d

## To - Do

- [x] Add curent users name to the fullscreen mode
- [x] add how far throught they are in fullscreen mode. e.g. 14/43 (32.6%)
- [ ] add hide photo for counting button in admin console
- [x] add delete photo and photo data in admin conlole
- [x] add delete all data in admin consle
- [x] move delete buttons and download as json to a differant part of the screen
- [x] make actual image in fullscreen mode look bigger
- [x] adda set user dropdown to go back and change a specific user's votes
- [x] add support for yes no votes as well as star ratings
- [x] make it so that a users ratings appear as soon as they exit fullscreen, not only after page reload
- [ ] add multi image set funcanality
- [ ] add pw to admin pannel
