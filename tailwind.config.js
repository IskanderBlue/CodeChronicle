/** @type {import('tailwindcss').Config} */
const colors = require('tailwindcss/colors')
module.exports = {
  content: ['templates/**/*.html'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: colors.teal,
        accent: colors.yellow,
        neutral: colors.slate,
        danger: colors.red,
        success: colors.green,
      }
    }
  }
}
