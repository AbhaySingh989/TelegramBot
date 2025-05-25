def reverse_alphabet(text: str) -> str:
    """Reverses the alphabet of each letter in a string, leaving non-alphabetic characters untouched.

    Args:
        text: The input string.

    Returns:
        A new string with each letter replaced by its reverse alphabet counterpart.
        For example, 'a' becomes 'z', 'b' becomes 'y', 'A' becomes 'Z', etc.
    """
    result = []
    for char in text:
        if 'a' <= char <= 'z':
            # Calculate the reversed character for lowercase letters
            reversed_char = chr(ord('a') + (ord('z') - ord(char)))
            result.append(reversed_char)
        elif 'A' <= char <= 'Z':
            # Calculate the reversed character for uppercase letters
            reversed_char = chr(ord('A') + (ord('Z') - ord(char)))
            result.append(reversed_char)
        else:
            # Keep non-alphabetic characters as they are
            result.append(char)
    return "".join(result)
