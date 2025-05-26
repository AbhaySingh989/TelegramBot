def generate_topic_dot_string(topic_str: str, index: int) -> str:
    """
    Replicates the logic of the corrected line 753 of New_Main.py
    for generating a portion of the DOT string for a single topic.
    """
    # Logic from the list comprehension:
    # topic.strip().replace("-", "_").replace(" ", "_").replace("'", "").replace("`", "").replace("\"", "\\\"")
    processed_topic = topic_str.strip().replace("-", "_").replace(" ", "_").replace("'", "").replace("`", "").replace("\"", "\\\"")
    return f'topic{index} [label="Topic: {processed_topic}", fillcolor="lightgreen"]; main -> topic{index};'

def main():
    test_topics_input = [
        "Work",
        "Personal Growth",
        "Day-to-day tasks",
        "John's project",
        "```code example```",
        'Topic with "quotes"',
        'Test "Topic" - for \'project\' & `code`',
        "",
        "N/A",
        "N/A stuff",
        'Another "complex" example with `backticks` and \'single quotes\''
    ]

    # Simulate the topics string as it would be before split(',')
    topics_string = ",".join(test_topics_input)
    
    print("--- Test Results for Topic String Generation ---")
    
    generated_dot_parts = []
    
    # Simulate the loop and conditions from the original line:
    # ... for i, topic in enumerate(str(topics).split(',')) if topic.strip() and topic != 'N/A']
    for i, topic_from_split in enumerate(topics_string.split(',')):
        original_topic_for_print = topic_from_split # Preserve for printing before strip
        
        # Apply the condition: if topic.strip() and topic != 'N/A'
        topic_stripped = topic_from_split.strip()
        if topic_stripped and topic_stripped != 'N/A':
            generated_string = generate_topic_dot_string(topic_stripped, i) # Pass stripped to function
            generated_dot_parts.append(generated_string)
            print(f"Original Topic : '{original_topic_for_print}'")
            print(f"Generated String: {generated_string}\n")
        else:
            print(f"Original Topic : '{original_topic_for_print}' (Skipped)\n")

    # Simulate the final ' '.join(...)
    final_topics_dot_str = ' '.join(generated_dot_parts)
    print("--- Final Combined DOT String (Simulated) ---")
    print(final_topics_dot_str)
    print("\n--- Analysis ---")
    if 'SyntaxError' in final_topics_dot_str:
        print("Potential SyntaxError: Found 'SyntaxError' in the output. This is unexpected.")
    else:
        print("No 'SyntaxError' string found in the output.")

    # Check for correct double quote escaping
    # For 'Topic with "quotes"' expected: 'Topic with \\"quotes\\"' in label
    # For 'Test "Topic" - for \'project\' & `code`' expected: 'Test \\"Topic\\" - for project & code'
    # For 'Another "complex" example with `backticks` and \'single quotes\'' expected: 'Another \\"complex\\" example with backticks and single quotes'
    
    correct_escaping_count = 0
    expected_escaped_outputs = {
        'Topic with "quotes"': 'label="Topic: Topic_with_\\"quotes\\"",',
        'Test "Topic" - for \'project\' & `code`': 'label="Topic: Test_\\"Topic\\"_-_for_project_&_code",',
        'Another "complex" example with `backticks` and \'single quotes\'': 'label="Topic: Another_\\"complex\\"_example_with_backticks_and_single_quotes",'
    }

    for topic_input, expected_label_part in expected_escaped_outputs.items():
        found = False
        for part in generated_dot_parts:
            # We need to check the processed topic string within the label
            # Re-process the topic_input to match how it would be in the label for comparison
            processed_input_for_label = topic_input.strip().replace("-", "_").replace(" ", "_").replace("'", "").replace("`", "").replace("\"", "\\\"")
            expected_full_label = f'label="Topic: {processed_input_for_label}"'
            if expected_full_label in part:
                found = True
                correct_escaping_count +=1
                print(f"PASSED: Correct escaping for input: '{topic_input}' -> ...{expected_full_label}...")
                break
        if not found:
             print(f"FAILED: Expected escaping not found for input: '{topic_input}'. Expected label part: ...{expected_label_part}...")
             # Attempt to find what was actually generated for this specific input
             for i, tfs in enumerate(topics_string.split(',')):
                 if tfs.strip() == topic_input: # Check against stripped version
                     if tfs.strip() and tfs.strip() != 'N/A': # Ensure it wasn't skipped
                        generated_str_for_failed = generate_topic_dot_string(tfs.strip(), i)
                        print(f"  Actually generated for '{topic_input}': {generated_str_for_failed}")
                     break


    if correct_escaping_count == len(expected_escaped_outputs):
        print("All tested double quote escapings are correct.")
    else:
        print(f"Found {correct_escaping_count} correct double quote escapings out of {len(expected_escaped_outputs)} tested cases.")

if __name__ == "__main__":
    main()
